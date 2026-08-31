const scenario = ({ id, label, openingSignals, turns }) => ({
  id,
  label,
  openingSignals,
  turns,
});

export const demoScenarios = [
  scenario({
    id: 'buying',
    label: 'Buying',
    openingSignals: ['jewelry necklaces', 'material alloy'],
    turns: [
      {
        customer: "I'm looking for Jewelry Necklaces. A key requirement is: Material: alloy.",
        assistant: "Here's my strongest match so far. Tell me anything else that matters — details, features, must-haves.",
        action: { value: 'other', label: 'Other details' },
        preferences: ['Jewelry necklaces', 'Alloy'],
        recommendation: {
          name: 'QIAN0813 Celtic Knot Triple Moon Pentacle Pendant Necklace',
          asin: 'B09PYB7B6Z',
          rank: 1,
        },
        isComplete: true,
      },
    ],
  }),
  scenario({
    id: 'browsing',
    label: 'Browsing',
    openingSignals: ['basketball men', 'still exploring'],
    turns: [
      {
        customer: "I'm looking for Basketball Men, but I'm still exploring.",
        assistant: "Here's my strongest match so far. Which specific features matter most to you?",
        action: { value: 'feature', label: 'Product features' },
        preferences: ['Basketball men', 'Exploring'],
        recommendation: {
          name: "Pro Club Men's Heavyweight Mesh Basketball Shorts",
          asin: 'B071F2Z7JG',
          rank: 1,
        },
        isComplete: true,
      },
    ],
  }),
  scenario({
    id: 'intent-override',
    label: 'Intent Override',
    openingSignals: ['watches wrist watches', 'stainless steel band'],
    turns: [
      {
        customer: "I'm looking for Watches Wrist Watches. Stainless Steel Band",
        assistant: 'Tell me anything else that matters — details, features, must-haves.',
        action: { value: 'other', label: 'Other details' },
        preferences: ['Wrist watches', 'Stainless steel band'],
      },
      {
        customer: 'For that, what matters is: Water Resistant; 3 Year Battery.',
        assistant: 'Tell me anything else that matters — details, features, must-haves.',
        action: { value: 'other', label: 'Other details' },
        preferences: ['Wrist watches', 'Stainless steel band', 'Water resistant', '3 year battery'],
      },
      {
        customer: 'Actually, ignore my earlier preference. What I need is: Water Resistant.',
        assistant: "Here's my strongest match so far. Tell me anything else that matters — details, features, must-haves.",
        action: { value: 'other', label: 'Other details' },
        preferences: ['Wrist watches', 'Water resistant'],
        removedPreferences: ['Stainless steel band', '3 year battery'],
        recommendation: {
          name: "Casio Men's Wrist Watch AQ-800E-7A",
          asin: 'B09YMTWDXJ',
          rank: 1,
        },
        isComplete: true,
      },
    ],
  }),
  scenario({
    id: 'boundary',
    label: 'Boundary',
    openingSignals: ['athletic walking', 'still exploring'],
    turns: [
      {
        customer: "I'm looking for Athletic Walking, but I'm still exploring.",
        assistant: "Here's my strongest match so far. Tell me anything else that matters — details, features, must-haves.",
        action: { value: 'other', label: 'Other details' },
        preferences: ['Athletic walking', 'Exploring'],
        candidateStatus: 'Current candidate updated',
      },
      {
        customer: "I don't have a preference for other; please use your judgment.",
        assistant: "Here's my strongest match so far. Tell me anything else that matters — details, features, must-haves.",
        action: { value: 'other', label: 'Other details' },
        preferences: ['Athletic walking', 'No preference for other'],
        candidateStatus: 'Current candidate updated',
      },
      {
        customer: 'For that, what matters is: fabric; 100% Textile.',
        assistant: "Here's my strongest match so far. Tell me anything else that matters — details, features, must-haves.",
        action: { value: 'other', label: 'Other details' },
        preferences: ['Athletic walking', 'Fabric', '100% textile'],
        recommendation: {
          name: "Skechers Men's Go Max Athletic Air Mesh Slip-on Walking Shoe",
          asin: 'B0BN6CCHB7',
          rank: 1,
        },
        isComplete: true,
      },
    ],
  }),
];

export function normalizeDemoMessage(value) {
  return value
    .toLowerCase()
    .replace(/[’‘]/g, "'")
    .replace(/[^a-z0-9%]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export function detectDemoScenario(message) {
  const normalized = normalizeDemoMessage(message);
  return demoScenarios.find(({ openingSignals }) => (
    openingSignals.every((signal) => normalized.includes(signal))
  ));
}

export function getDemoScenario(id) {
  return demoScenarios.find((item) => item.id === id);
}

export function matchesDemoTurn(message, expectedMessage) {
  return normalizeDemoMessage(message) === normalizeDemoMessage(expectedMessage);
}
