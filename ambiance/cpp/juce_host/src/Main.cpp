#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_gui_extra/juce_gui_extra.h>

#include <optional>

namespace
{

constexpr int defaultWidth = 900;
constexpr int defaultHeight = 600;
constexpr double defaultSampleRate = 48000.0;
constexpr int defaultBlockSize = 512;

class PluginComponent : public juce::Component,
                        private juce::Timer
{
public:
    explicit PluginComponent(const juce::File& pluginCandidate)
    {
        formatManager.addDefaultFormats();

        auto resolvedPlugin = resolvePluginSource(pluginCandidate);
        if (!resolvedPlugin.has_value())
            return;

        if (!initialisePluginInstance(*resolvedPlugin))
            return;

        auto audioError = deviceManager.initialiseWithDefaultDevices(instance->getTotalNumInputChannels(),
                                                                     juce::jmax(1, instance->getTotalNumOutputChannels()));
        if (audioError.isNotEmpty())
        {
            errorMessage = audioError;
            teardownInstance();
            return;
        }

        deviceManager.addAudioCallback(&player);
        deviceManager.addMidiInputCallback({}, &player);
        player.setProcessor(instance.get());

        editor.reset(instance->createEditor());
        if (editor == nullptr)
        {
            errorMessage = "Plugin does not provide a UI editor.";
            teardownInstance();
            return;
        }

        addAndMakeVisible(editor.get());
        setSize(editor->getWidth(), editor->getHeight());
        startTimerHz(30);
    }

    ~PluginComponent() override
    {
        stopTimer();
        teardownInstance();
        if (extractedTempRoot.isDirectory())
            extractedTempRoot.deleteRecursively();
    }

    bool isValid() const noexcept { return instance != nullptr && editor != nullptr && errorMessage.isEmpty(); }

    juce::String getError() const { return errorMessage; }

    void resized() override
    {
        if (editor != nullptr)
            editor->setBounds(getLocalBounds());
    }

private:
    struct ResolvedPlugin
    {
        juce::File location;
        juce::File extractionRoot;
    };

    std::optional<ResolvedPlugin> resolvePluginSource(const juce::File& candidate)
    {
        if (!candidate.exists())
        {
            errorMessage = "Plugin path does not exist: " + candidate.getFullPathName();
            return std::nullopt;
        }

        if (candidate.hasFileExtension("zip"))
        {
            auto extracted = extractZipArchive(candidate);
            if (!extracted.isDirectory())
                return std::nullopt;

            auto plugin = locatePluginEntry(extracted);
            if (!plugin.exists())
            {
                errorMessage = "No VST plugin found inside zip archive: " + candidate.getFullPathName();
                extracted.deleteRecursively();
                return std::nullopt;
            }

            return ResolvedPlugin{plugin, extracted};
        }

        if (candidate.isDirectory())
        {
            auto plugin = locatePluginEntry(candidate);
            if (plugin.exists())
                return ResolvedPlugin{plugin, {}};

            errorMessage = "Unable to locate a plugin inside " + candidate.getFullPathName();
            return std::nullopt;
        }

        if (candidate.existsAsFile())
            return ResolvedPlugin{candidate, {}};

        errorMessage = "Unsupported plugin path: " + candidate.getFullPathName();
        return std::nullopt;
    }

    juce::File extractZipArchive(const juce::File& zipFile)
    {
        auto tempRoot = juce::File::getSpecialLocation(juce::File::tempDirectory)
                             .getChildFile("ambiance_plugin_" + juce::Uuid().toString());

        if (!tempRoot.createDirectory())
        {
            errorMessage = "Unable to create temporary directory for zip extraction.";
            return {};
        }

        juce::ZipFile archive(zipFile);
        if (archive.getNumEntries() == 0 || !archive.uncompressTo(tempRoot))
        {
            errorMessage = "Failed to extract zip archive: " + zipFile.getFileName();
            tempRoot.deleteRecursively();
            return {};
        }

        return tempRoot;
    }

    static juce::File locatePluginEntry(const juce::File& root)
    {
        if (isSupportedPluginPath(root))
            return root;

        if (!root.isDirectory())
            return {};

        juce::DirectoryIterator iterator(root, true, "*", juce::File::findFilesAndDirectories);
        while (iterator.next())
        {
            auto file = iterator.getFile();
            if (isSupportedPluginPath(file))
                return file;
        }

        return {};
    }

    static bool isSupportedPluginPath(const juce::File& file)
    {
        return file.hasFileExtension("vst3") || file.hasFileExtension("dll") || file.hasFileExtension("vst")
               || file.hasFileExtension("component") || file.hasFileExtension("vstbundle");
    }

    bool initialisePluginInstance(const ResolvedPlugin& resolved)
    {
        extractedTempRoot = resolved.extractionRoot;

        juce::StringArray errorMessages;
        for (int i = 0; i < formatManager.getNumFormats(); ++i)
        {
            auto* format = formatManager.getFormat(i);
            if (format == nullptr)
                continue;

            if (!format->fileMightContainThisPluginType(resolved.location.getFullPathName()))
                continue;

            juce::OwnedArray<juce::PluginDescription> descriptions;
            format->findAllTypesForFile(descriptions, resolved.location.getFullPathName());

            if (descriptions.isEmpty())
            {
                errorMessages.add(format->getName() + ": No plugin descriptions found for "
                                  + resolved.location.getFullPathName());
                continue;
            }

            for (auto* description : descriptions)
            {
                if (description == nullptr)
                    continue;

                juce::String instantiationError;
                if (tryCreatePluginInstance(*format, *description, instantiationError))
                    return true;

                if (instantiationError.isNotEmpty())
                    errorMessages.add(format->getName() + " (" + description->name + "): " + instantiationError);
            }
        }

        if (errorMessages.isEmpty())
            errorMessage = "No compatible plugin format found for " + resolved.location.getFullPathName();
        else
            errorMessage = "Unable to create plugin instance:\n" + errorMessages.joinIntoString("\n");

        return false;
    }

    bool tryCreatePluginInstance(juce::AudioPluginFormat& format,
                                 const juce::PluginDescription& description,
                                 juce::String& failureReason)
    {
        if (format.requiresUnblockedMessageThreadDuringCreation(description))
            return createInstanceAsynchronously(format, description, failureReason);

        juce::String error;
        auto createdInstance = formatManager.createPluginInstance(description, defaultSampleRate, defaultBlockSize, error);
        if (createdInstance != nullptr)
        {
            instance = std::move(createdInstance);
            return true;
        }

        failureReason = error.isNotEmpty() ? error : "Unknown error returned while creating plugin instance.";
        return false;
    }

    bool createInstanceAsynchronously(juce::AudioPluginFormat& format,
                                      const juce::PluginDescription& description,
                                      juce::String& failureReason)
    {
        juce::WaitableEvent finished;
        juce::String asyncError;
        std::unique_ptr<juce::AudioPluginInstance> createdInstance;

        format.createPluginInstanceAsync(description,
                                         defaultSampleRate,
                                         defaultBlockSize,
                                         [this, &finished, &asyncError, &createdInstance](std::unique_ptr<juce::AudioPluginInstance> instanceCreated,
                                                                                           const juce::String& error) mutable {
                                             if (instanceCreated != nullptr)
                                                 createdInstance = std::move(instanceCreated);

                                             asyncError = error;
                                             finished.signal();
                                         });

        constexpr int pollIntervalMs = 20;
        constexpr int timeoutMs = 30000;
        int waitedMs = 0;

        while (!finished.wait(pollIntervalMs))
        {
            if (auto* messageManager = juce::MessageManager::getInstanceWithoutCreating(); messageManager != nullptr
                && messageManager->isThisTheMessageThread())
            {
                messageManager->runDispatchLoopUntil(pollIntervalMs);
            }
            else
            {
                juce::Thread::sleep(pollIntervalMs);
            }

            waitedMs += pollIntervalMs;
            if (waitedMs >= timeoutMs)
            {
                failureReason = "Timed out while creating plugin instance.";
                return false;
            }
        }

        if (createdInstance != nullptr)
        {
            instance = std::move(createdInstance);
            return true;
        }

        failureReason = asyncError.isNotEmpty() ? asyncError : "Unknown error returned during asynchronous instantiation.";
        return false;
    }

    void teardownInstance()
    {
        player.setProcessor(nullptr);
        deviceManager.removeMidiInputCallback({}, &player);
        deviceManager.removeAudioCallback(&player);
        editor.reset();
        instance.reset();
    }

    void timerCallback() override
    {
        if (editor == nullptr)
            return;

        const auto bounds = getLocalBounds();
        if (bounds.getWidth() != editor->getWidth() || bounds.getHeight() != editor->getHeight())
            setSize(editor->getWidth(), editor->getHeight());
    }

    juce::AudioPluginFormatManager formatManager;
    std::unique_ptr<juce::AudioPluginInstance> instance;
    std::unique_ptr<juce::AudioProcessorEditor> editor;
    juce::AudioDeviceManager deviceManager;
    juce::AudioProcessorPlayer player;
    juce::File extractedTempRoot;
    juce::String errorMessage;
};

class MainWindow : public juce::DocumentWindow
{
public:
    MainWindow(const juce::String& title, const juce::File& plugin)
        : DocumentWindow(title,
                         juce::Desktop::getInstance().getDefaultLookAndFeel().findColour(juce::ResizableWindow::backgroundColourId),
                         DocumentWindow::allButtons)
    {
        setUsingNativeTitleBar(true);
        setResizable(true, false);
        setVisible(true);

        auto component = std::make_unique<PluginComponent>(plugin);
        if (!component->isValid())
        {
            juce::AlertWindow::showMessageBoxAsync(juce::MessageBoxIconType::WarningIcon,
                                                   "Unable to load plugin",
                                                   component->getError());
            setContentOwned(new juce::Component(), true);
            centreWithSize(defaultWidth, defaultHeight);
            return;
        }

        auto width = juce::jmax(component->getWidth(), defaultWidth);
        auto height = juce::jmax(component->getHeight(), defaultHeight);
        setContentOwned(component.release(), true);
        centreWithSize(width, height);
    }

    void closeButtonPressed() override
    {
        juce::JUCEApplication::getInstance()->systemRequestedQuit();
    }
};

class HostApplication : public juce::JUCEApplication
{
public:
    HostApplication() = default;

    const juce::String getApplicationName() override { return "Ambiance JUCE Plugin Host"; }
    const juce::String getApplicationVersion() override { return "0.1.0"; }

    void initialise(const juce::String& commandLine) override
    {
        juce::File pluginFile;

        if (commandLine.isNotEmpty())
        {
            pluginFile = juce::File::getCurrentWorkingDirectory().getChildFile(commandLine.trim());
            if (!pluginFile.existsAsFile())
                pluginFile = juce::File(commandLine.trim());
        }

        if (!pluginFile.existsAsFile())
        {
            juce::FileChooser chooser("Select a VST3 plugin to load",
                                      juce::File::getSpecialLocation(juce::File::userHomeDirectory),
                                      "*.vst3");
            if (!chooser.browseForFileToOpen())
            {
                juce::JUCEApplication::quit();
                return;
            }
            pluginFile = chooser.getResult();
        }

        mainWindow = std::make_unique<MainWindow>(getApplicationName(), pluginFile);
    }

    void shutdown() override { mainWindow.reset(); }

private:
    std::unique_ptr<MainWindow> mainWindow;
};

} // namespace

START_JUCE_APPLICATION(HostApplication)

