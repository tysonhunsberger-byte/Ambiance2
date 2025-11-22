(function initAmbianceDrumData(global) {
    if (global.AmbianceDrumData) {
        return;
    }

    const DRUM_BANK_DATA = {
  "9000": {
    "bank": "9000",
    "instruments": {
      "bd": 1,
      "cb": 2,
      "cr": 2,
      "hh": 1,
      "ht": 2,
      "lt": 2,
      "mt": 1,
      "oh": 1,
      "perc": 3,
      "rd": 2,
      "rim": 1,
      "sd": 1,
      "tb": 1
    },
    "label": "9000"
  },
  "ace": {
    "bank": "ace",
    "instruments": {
      "bd": 3,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "oh": 1,
      "perc": 6,
      "sd": 3
    },
    "label": "Ace"
  },
  "circuitsdrumtracks": {
    "bank": "circuitsdrumtracks",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "oh": 1,
      "rd": 1,
      "rim": 1,
      "sd": 1,
      "sh": 1,
      "tb": 1
    },
    "label": "CircuitsDrumtracks"
  },
  "circuitstom": {
    "bank": "circuitstom",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 2,
      "oh": 1,
      "sd": 1
    },
    "label": "CircuitsTom"
  },
  "compurhythm1000": {
    "bank": "compurhythm1000",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 3,
      "rd": 1,
      "rim": 1,
      "sd": 1
    },
    "label": "Compurhythm1000"
  },
  "compurhythm78": {
    "bank": "compurhythm78",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "hh": 2,
      "misc": 4,
      "oh": 2,
      "perc": 8,
      "sd": 1,
      "tb": 1
    },
    "label": "Compurhythm78"
  },
  "compurhythm8000": {
    "bank": "compurhythm8000",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 2,
      "rim": 1,
      "sd": 1
    },
    "label": "Compurhythm8000"
  },
  "concertmatemg1": {
    "bank": "concertmatemg1",
    "instruments": {
      "bd": 3,
      "sd": 2
    },
    "label": "ConcertMateMG1"
  },
  "d110": {
    "bank": "d110",
    "instruments": {
      "bd": 1,
      "cb": 2,
      "cr": 1,
      "hh": 1,
      "lt": 1,
      "oh": 2,
      "perc": 3,
      "rd": 1,
      "rim": 1,
      "sd": 3,
      "sh": 1,
      "tb": 1
    },
    "label": "D110"
  },
  "d70": {
    "bank": "d70",
    "instruments": {
      "bd": 4,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 1,
      "rd": 1,
      "rim": 1,
      "sd": 5,
      "sh": 1
    },
    "label": "D70"
  },
  "ddm110": {
    "bank": "ddm110",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 2,
      "lt": 2,
      "oh": 1,
      "rim": 1,
      "sd": 1
    },
    "label": "DDM110"
  },
  "ddr30": {
    "bank": "ddr30",
    "instruments": {
      "bd": 8,
      "ht": 4,
      "lt": 4,
      "sd": 8
    },
    "label": "DDR30"
  },
  "dmx": {
    "bank": "dmx",
    "instruments": {
      "": 3,
      "bd": 3,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "rd": 1,
      "rim": 1,
      "sd": 3,
      "sh": 1,
      "tb": 1
    },
    "label": "DMX"
  },
  "dpm48": {
    "bank": "dpm48",
    "instruments": {
      "bd": 3,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 1,
      "lt": 2,
      "mt": 1,
      "oh": 1,
      "perc": 2,
      "rd": 1,
      "rim": 1,
      "sd": 2,
      "sh": 2
    },
    "label": "DPM48"
  },
  "dr110": {
    "bank": "dr110",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "oh": 1,
      "rd": 1,
      "sd": 1
    },
    "label": "DR110"
  },
  "dr220": {
    "bank": "dr220",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 1,
      "rd": 1,
      "sd": 1
    },
    "label": "DR220"
  },
  "dr55": {
    "bank": "dr55",
    "instruments": {
      "bd": 2,
      "hh": 2,
      "rim": 1,
      "sd": 8
    },
    "label": "DR55"
  },
  "dr550": {
    "bank": "dr550",
    "instruments": {
      "bd": 5,
      "cb": 2,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 3,
      "lt": 3,
      "misc": 3,
      "mt": 2,
      "oh": 2,
      "perc": 11,
      "rd": 2,
      "rim": 1,
      "sd": 6,
      "sh": 2,
      "tb": 1
    },
    "label": "DR550"
  },
  "drumulator": {
    "bank": "drumulator",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 1,
      "rim": 1,
      "sd": 1
    },
    "label": "Drumulator"
  },
  "emumodular": {
    "bank": "emumodular",
    "instruments": {
      "bd": 2,
      "misc": 1,
      "perc": 2
    },
    "label": "Emu Modular"
  },
  "hr16": {
    "bank": "hr16",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "oh": 1,
      "perc": 8,
      "rim": 1,
      "sd": 1,
      "sh": 3
    },
    "label": "HR16"
  },
  "jd990": {
    "bank": "jd990",
    "instruments": {
      "bd": 10,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 4,
      "ht": 1,
      "lt": 5,
      "misc": 12,
      "mt": 2,
      "oh": 2,
      "perc": 6,
      "rd": 1,
      "sd": 15,
      "tb": 1
    },
    "label": "JD990"
  },
  "kpr77": {
    "bank": "kpr77",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "hh": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "KPR77"
  },
  "kr55": {
    "bank": "kr55",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "oh": 1,
      "perc": 2,
      "rim": 1,
      "sd": 1
    },
    "label": "KR55"
  },
  "krz": {
    "bank": "krz",
    "instruments": {
      "bd": 1,
      "cr": 1,
      "fx": 2,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "misc": 1,
      "oh": 1,
      "rd": 1,
      "sd": 2
    },
    "label": "KRZ"
  },
  "linn": {
    "bank": "linn",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "rd": 1,
      "sd": 1,
      "sh": 1,
      "tb": 1
    },
    "label": "Linn"
  },
  "linndrum": {
    "bank": "linndrum",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 3,
      "ht": 2,
      "lt": 2,
      "mt": 1,
      "oh": 1,
      "perc": 6,
      "rd": 1,
      "rim": 3,
      "sd": 3,
      "sh": 1,
      "tb": 1
    },
    "label": "Linn Drum"
  },
  "lm1": {
    "bank": "lm1",
    "instruments": {
      "bd": 4,
      "cb": 1,
      "cp": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "oh": 1,
      "perc": 3,
      "rim": 1,
      "sd": 1,
      "sh": 1,
      "tb": 1
    },
    "label": "LM1"
  },
  "lm2": {
    "bank": "lm2",
    "instruments": {
      "bd": 4,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 2,
      "rd": 1,
      "rim": 2,
      "sd": 4,
      "sh": 1,
      "tb": 1
    },
    "label": "LM2"
  },
  "lm8953": {
    "bank": "lm8953",
    "instruments": {
      "bd": 3,
      "cr": 1,
      "hh": 2,
      "ht": 2,
      "lt": 2,
      "mt": 2,
      "oh": 1,
      "rd": 1,
      "rim": 2,
      "sd": 5,
      "tb": 1
    },
    "label": "LM8953"
  },
  "m1": {
    "bank": "m1",
    "instruments": {
      "bd": 3,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 2,
      "misc": 16,
      "mt": 1,
      "oh": 2,
      "perc": 7,
      "rd": 1,
      "rim": 1,
      "sd": 4,
      "sh": 1,
      "tb": 1
    },
    "label": "M1"
  },
  "mc202": {
    "bank": "mc202",
    "instruments": {
      "bd": 5,
      "ht": 3,
      "perc": 1
    },
    "label": "MC202"
  },
  "mc303": {
    "bank": "mc303",
    "instruments": {
      "bd": 16,
      "cb": 2,
      "cp": 8,
      "fx": 2,
      "hh": 6,
      "ht": 5,
      "lt": 5,
      "misc": 8,
      "mt": 6,
      "oh": 5,
      "perc": 39,
      "rd": 2,
      "rim": 6,
      "sd": 26,
      "sh": 7,
      "tb": 5
    },
    "label": "MC303"
  },
  "mfb512": {
    "bank": "mfb512",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "M F B512"
  },
  "microrhythmer12": {
    "bank": "microrhythmer12",
    "instruments": {
      "bd": 1,
      "hh": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "MicroRhythmer12"
  },
  "minipops": {
    "bank": "minipops",
    "instruments": {
      "bd": 7,
      "hh": 4,
      "misc": 4,
      "oh": 4,
      "sd": 13
    },
    "label": "Minipops"
  },
  "mpc1000": {
    "bank": "mpc1000",
    "instruments": {
      "bd": 5,
      "cp": 1,
      "hh": 4,
      "oh": 1,
      "perc": 1,
      "sd": 4,
      "sh": 1
    },
    "label": "M P C1000"
  },
  "mpc60": {
    "bank": "mpc60",
    "instruments": {
      "bd": 2,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "misc": 2,
      "mt": 1,
      "oh": 1,
      "perc": 5,
      "rd": 1,
      "rim": 1,
      "sd": 3
    },
    "label": "MPC60"
  },
  "ms404": {
    "bank": "ms404",
    "instruments": {
      "bd": 2,
      "hh": 1,
      "lt": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "MS404"
  },
  "mt32": {
    "bank": "mt32",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 2,
      "perc": 13,
      "rd": 1,
      "rim": 1,
      "sd": 2,
      "sh": 2,
      "tb": 1
    },
    "label": "MT32"
  },
  "percysyn": {
    "bank": "percysyn",
    "instruments": {
      "bd": 1,
      "cb": 2,
      "ht": 1,
      "sd": 1
    },
    "label": "Percysyn"
  },
  "polaris": {
    "bank": "polaris",
    "instruments": {
      "bd": 4,
      "misc": 4,
      "sd": 4
    },
    "label": "Polaris"
  },
  "poly800": {
    "bank": "poly800",
    "instruments": {
      "bd": 4
    },
    "label": "Poly800"
  },
  "r8": {
    "bank": "r8",
    "instruments": {
      "bd": 7,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 4,
      "lt": 4,
      "mt": 4,
      "oh": 1,
      "perc": 8,
      "rd": 2,
      "rim": 2,
      "sd": 12,
      "sh": 2,
      "tb": 1
    },
    "label": "R8"
  },
  "r88": {
    "bank": "r88",
    "instruments": {
      "bd": 1,
      "cr": 1,
      "hh": 1,
      "oh": 1,
      "sd": 2
    },
    "label": "R88"
  },
  "rm50": {
    "bank": "rm50",
    "instruments": {
      "bd": 103,
      "cb": 6,
      "cp": 2,
      "cr": 22,
      "hh": 18,
      "ht": 25,
      "lt": 49,
      "misc": 28,
      "mt": 34,
      "oh": 12,
      "perc": 56,
      "rd": 13,
      "sd": 108,
      "sh": 6,
      "tb": 3
    },
    "label": "RM50"
  },
  "rx21": {
    "bank": "rx21",
    "instruments": {
      "bd": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "RX21"
  },
  "rx5": {
    "bank": "rx5",
    "instruments": {
      "bd": 2,
      "cb": 1,
      "fx": 1,
      "hh": 1,
      "lt": 1,
      "oh": 1,
      "rim": 1,
      "sd": 3,
      "sh": 1,
      "tb": 1
    },
    "label": "RX5"
  },
  "ry30": {
    "bank": "ry30",
    "instruments": {
      "bd": 13,
      "cb": 2,
      "cp": 1,
      "cr": 2,
      "hh": 4,
      "ht": 3,
      "lt": 3,
      "misc": 8,
      "mt": 2,
      "oh": 4,
      "perc": 13,
      "rd": 3,
      "rim": 2,
      "sd": 21,
      "sh": 2,
      "tb": 1
    },
    "label": "RY30"
  },
  "rz1": {
    "bank": "rz1",
    "instruments": {
      "bd": 1,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "rd": 2,
      "rim": 1,
      "sd": 1
    },
    "label": "RZ1"
  },
  "s50": {
    "bank": "s50",
    "instruments": {
      "bd": 4,
      "cb": 1,
      "cp": 1,
      "cr": 2,
      "ht": 1,
      "lt": 2,
      "misc": 6,
      "mt": 1,
      "oh": 1,
      "perc": 14,
      "rd": 1,
      "sd": 3,
      "sh": 4,
      "tb": 2
    },
    "label": "S50"
  },
  "sds400": {
    "bank": "sds400",
    "instruments": {
      "ht": 3,
      "lt": 6,
      "mt": 8,
      "sd": 3
    },
    "label": "SDS400"
  },
  "sds5": {
    "bank": "sds5",
    "instruments": {
      "bd": 12,
      "hh": 5,
      "ht": 3,
      "lt": 8,
      "mt": 6,
      "oh": 2,
      "rim": 7,
      "sd": 21
    },
    "label": "SDS5"
  },
  "sergemodular": {
    "bank": "sergemodular",
    "instruments": {
      "bd": 1,
      "misc": 1,
      "perc": 5
    },
    "label": "Serge Modular"
  },
  "sh09": {
    "bank": "sh09",
    "instruments": {
      "bd": 43
    },
    "label": "SH09"
  },
  "sk1": {
    "bank": "sk1",
    "instruments": {
      "bd": 1,
      "hh": 1,
      "ht": 1,
      "mt": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "SK1"
  },
  "sp12": {
    "bank": "sp12",
    "instruments": {
      "bd": 14,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 2,
      "ht": 6,
      "lt": 6,
      "misc": 7,
      "mt": 4,
      "oh": 1,
      "perc": 1,
      "rd": 1,
      "rim": 2,
      "sd": 21
    },
    "label": "SP12"
  },
  "spacedrum": {
    "bank": "spacedrum",
    "instruments": {
      "bd": 11,
      "cb": 1,
      "hh": 6,
      "ht": 7,
      "lt": 2,
      "misc": 2,
      "mt": 2,
      "oh": 3,
      "perc": 2,
      "rim": 1,
      "sd": 3
    },
    "label": "SpaceDrum"
  },
  "sr16": {
    "bank": "sr16",
    "instruments": {
      "bd": 13,
      "cb": 1,
      "cp": 1,
      "cr": 2,
      "hh": 3,
      "misc": 3,
      "oh": 4,
      "perc": 7,
      "rd": 3,
      "rim": 1,
      "sd": 12,
      "sh": 1,
      "tb": 1
    },
    "label": "SR16"
  },
  "system100": {
    "bank": "system100",
    "instruments": {
      "bd": 15,
      "hh": 2,
      "misc": 2,
      "oh": 3,
      "perc": 19,
      "sd": 21
    },
    "label": "System100"
  },
  "t3": {
    "bank": "t3",
    "instruments": {
      "bd": 5,
      "cp": 1,
      "hh": 2,
      "misc": 4,
      "oh": 2,
      "perc": 4,
      "rim": 1,
      "sd": 5,
      "sh": 3
    },
    "label": "T3"
  },
  "tg33": {
    "bank": "tg33",
    "instruments": {
      "bd": 4,
      "cb": 3,
      "cp": 1,
      "cr": 3,
      "fx": 1,
      "ht": 2,
      "lt": 2,
      "misc": 10,
      "mt": 2,
      "oh": 1,
      "perc": 12,
      "rd": 2,
      "rim": 1,
      "sd": 5,
      "sh": 1,
      "tb": 1
    },
    "label": "TG33"
  },
  "tr505": {
    "bank": "tr505",
    "instruments": {
      "bd": 1,
      "cb": 2,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "perc": 3,
      "rd": 1,
      "rim": 1,
      "sd": 1
    },
    "label": "TR505"
  },
  "tr606": {
    "bank": "tr606",
    "instruments": {
      "bd": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "oh": 1,
      "sd": 1
    },
    "label": "TR606"
  },
  "tr626": {
    "bank": "tr626",
    "instruments": {
      "bd": 2,
      "cb": 1,
      "cp": 1,
      "cr": 2,
      "hh": 1,
      "ht": 2,
      "lt": 2,
      "mt": 2,
      "oh": 1,
      "perc": 8,
      "rd": 2,
      "rim": 1,
      "sd": 3,
      "sh": 1,
      "tb": 1
    },
    "label": "TR626"
  },
  "tr707": {
    "bank": "tr707",
    "instruments": {
      "bd": 2,
      "cb": 1,
      "cp": 1,
      "cr": 1,
      "hh": 1,
      "ht": 1,
      "lt": 1,
      "mt": 1,
      "oh": 1,
      "rim": 1,
      "sd": 2,
      "tb": 1
    },
    "label": "TR707"
  },
  "tr727": {
    "bank": "tr727",
    "instruments": {
      "perc": 10,
      "sh": 2
    },
    "label": "TR727"
  },
  "tr808": {
    "bank": "tr808",
    "instruments": {
      "bd": 25,
      "cb": 2,
      "cp": 5,
      "cr": 25,
      "hh": 1,
      "ht": 5,
      "lt": 5,
      "mt": 5,
      "oh": 5,
      "perc": 16,
      "rim": 1,
      "sd": 25,
      "sh": 2
    },
    "label": "TR808"
  },
  "tr909": {
    "bank": "tr909",
    "instruments": {
      "bd": 4,
      "cp": 5,
      "cr": 5,
      "hh": 4,
      "ht": 9,
      "lt": 9,
      "mt": 9,
      "oh": 5,
      "rd": 5,
      "rim": 3,
      "sd": 16
    },
    "label": "TR909"
  },
  "vl1": {
    "bank": "vl1",
    "instruments": {
      "bd": 1,
      "hh": 1,
      "sd": 1
    },
    "label": "VL1"
  },
  "xr10": {
    "bank": "xr10",
    "instruments": {
      "bd": 10,
      "cb": 1,
      "cp": 1,
      "cr": 3,
      "hh": 2,
      "ht": 1,
      "lt": 2,
      "misc": 4,
      "mt": 2,
      "oh": 1,
      "perc": 15,
      "rd": 1,
      "rim": 2,
      "sd": 10,
      "sh": 1,
      "tb": 1
    },
    "label": "XR10"
  }
};

    const fallbackKey = "tr909";
    const fallback = DRUM_BANK_DATA[fallbackKey] || {
        label: "TR-909",
        bank: "tr909",
        instruments: { bd: 4, sd: 4, hh: 4, oh: 4, cp: 2 },
    };

    global.AmbianceDrumData = Object.freeze({
        BANKS: DRUM_BANK_DATA,
        FALLBACK_BANK: fallback,
    });
})(window);
