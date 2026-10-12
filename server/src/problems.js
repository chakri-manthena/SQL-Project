/**
 * Problem definitions. The first source table of each problem is the one shown to
 * students; the remaining ones are hidden tests. Each source table is paired with the
 * destination table at the same index. Row order is only compared when `ordered` is set,
 * since SQL gives no ordering guarantee without ORDER BY.
 */
export const PROBLEMS = [
  {
    name: 'Problem 1',
    sourceTables: ['alpha', 'alpha2', 'alpha3'],
    destinationTables: ['alphad', 'alpha2d', 'alpha3d'],
    images: ['Problem 1.png'],
    repairable: true,
  },
  {
    name: 'Problem 2',
    sourceTables: ['bravo', 'bravo2'],
    destinationTables: ['bravod', 'bravo2d'],
    images: ['Problem 2.png'],
    repairable: true,
  },
  {
    name: 'Problem 3',
    sourceTables: ['charlie', 'charlie2', 'charlie3'],
    destinationTables: ['charlied', 'charlie2d', 'charlie3d'],
    images: ['Problem 3.png'],
    repairable: true,
  },
  {
    name: 'Problem 4',
    sourceTables: ['delta'],
    destinationTables: ['deltad'],
    images: ['Problem 4.png'],
    repairable: true,
  },
  {
    name: 'Problem 5',
    sourceTables: ['echo', 'echo2'],
    destinationTables: ['echod', 'echo2d'],
    images: ['Problem 5a.png', 'Problem 5b.png'],
    repairable: true,
  },
  {
    name: 'Problem 6',
    sourceTables: ['foxtrot', 'foxtrot2'],
    destinationTables: ['foxtrotd', 'foxtrot2d'],
    images: ['Problem 6a.png', 'Problem 6b.png'],
    repairable: true,
  },
  {
    name: 'Problem 7',
    sourceTables: ['golf', 'golf2'],
    destinationTables: ['golfd', 'golf2d'],
    images: ['Problem 7.png'],
    repairable: true,
  },
  {
    name: 'Problem 8',
    sourceTables: ['hotel', 'hotel2'],
    destinationTables: ['hoteld', 'hotel2d'],
    images: ['Problem 8.png'],
    repairable: true,
    ordered: true,
  },
  {
    name: 'Problem 9',
    sourceTables: ['india'],
    destinationTables: ['indiad'],
    images: ['Problem 9a.png', 'Problem 9b.png'],
    repairable: false,
  },
  {
    name: 'Problem 10',
    sourceTables: ['kilo', 'kilo2'],
    destinationTables: ['kilod', 'kilo2d'],
    images: ['Problem 10.png'],
    repairable: false,
  },
];

export function getProblem(name) {
  return PROBLEMS.find((p) => p.name === name) ?? null;
}

export const PROBLEM_GOALS = [
  'Return every column for rows whose MIN is 0.',
  "Return CUI1 and RUI for rows whose CUI2 is 'C0364349'.",
  'Return every column for rows whose CFR is at most 1634.',
  'Return RSAB and TFR for rows whose CFR is at most 1634.',
  "Return every column where MRRANK_RANK is below 380 or TTY is 'CD'.",
  "Return every column where TTY is 'PT', or TTY is 'SY' and MRRANK_RANK is above 400.",
  'Return distinct SVER values below 1996.',
  'Return every column, ordered by TUI descending and then CUI ascending.',
  'Join india and juliett on CUI. Return LAT, STT and ISPREF where CVF is not 256, retaining duplicate rows.',
  'Group by LUI and return LUI with the first inserted CUI for each group (SQLite representative-row behavior).',
];

/** Known-correct queries used to bootstrap voting before real students submit any. */
export const SEED_CORRECT_QUERIES = {
  'Problem 1': [
    'select * from alpha where MIN = 0',
    'SELECT * FROM alpha WHERE MIN = 0;',
    'select COL, DES, MIN, AV, MAX, FIL from alpha where min = 0 ',
    'SELECT * FROM alpha WHERE alpha.min = 0 ',
    "select * from alpha where min = '0'",
  ],
  'Problem 2': [
    "SELECT CUI1, RUI FROM bravo WHERE CUI2='C0364349'; ",
    "SELECT CUI1, RUI FROM bravo WHERE bravo.CUI2 = 'C0364349'  ",
    "select CUI1, RUI from bravo where CUI2 = 'C0364349'",
  ],
  'Problem 3': [
    'SELECT * FROM charlie WHERE TFR < 2000 && CFR < 1650 ',
    'SELECT * FROM charlie WHERE CFR < 1635',
    'select * from charlie where CFR < 1635',
  ],
  'Problem 4': [
    'select RSAB, TFR from delta where CFR < 1696',
    'SELECT RSAB, TFR FROM delta WHERE TFR < 1900 && CFR < 1650',
  ],
  'Problem 5': ["select * from echo where MRRANK_RANK < 380 or TTY = 'CD'"],
  'Problem 6': [
    "select * from foxtrot where TTY = 'PT' or (TTY = 'SY' and MRRANK_RANK > 400)",
    'SELECT * FROM foxtrot WHERE foxtrot.tty = "PT" OR foxtrot.tty = "SY" AND foxtrot.mrrank_rank > 400',
  ],
  'Problem 7': [
    'select distinct SVER from golf where SVER <= 1995',
    'SELECT DISTINCT SVER FROM golf WHERE SVER < 1996',
  ],
  'Problem 8': ['SELECT * from hotel ORDER BY TUI DESC, CUI ASC'],
};

/** Example repairs used when a participant has no repairable query of their own. */
export const SEED_REPAIRED_QUERIES = {
  'Problem 1': ['SELECT * FROM alpha WHERE MIN = 0'],
  'Problem 2': ["SELECT CUI1, RUI FROM bravo WHERE CUI2 = 'C0364349'"],
  'Problem 3': [
    'SELECT * FROM charlie WHERE CFR < 1635',
    'SELECT RSAB, SF, TFR, CFR, TTYL FROM charlie WHERE CFR <= 1634',
  ],
  'Problem 4': ['SELECT RSAB, TFR FROM delta WHERE CFR < 1635'],
  'Problem 5': [
    "SELECT * FROM echo WHERE TTY = 'CD' OR MRRANK_RANK < 380",
    "SELECT * FROM echo WHERE MRRANK_RANK < 380 OR TTY = 'CD'",
  ],
  'Problem 6': [
    "SELECT * FROM foxtrot WHERE TTY = 'PT' OR TTY = 'SY' AND MRRANK_RANK >= 400",
  ],
  'Problem 7': [
    'SELECT DISTINCT SVER FROM golf WHERE SVER < 1996',
    'SELECT DISTINCT SVER FROM golf WHERE SVER <= 1995',
  ],
  'Problem 8': [
    'SELECT * FROM hotel ORDER BY TUI DESC, CUI ASC',
    'SELECT CUI, TUI, STN FROM hotel ORDER BY TUI DESC, CUI',
  ],
};
