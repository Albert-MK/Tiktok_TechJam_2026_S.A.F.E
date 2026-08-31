import {
  detectDemoScenario,
  getDemoScenario,
  matchesDemoTurn,
} from '../data/demoScenarios';

const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

function guidance(message, suggestedReply = null) {
  return {
    message,
    kind: 'guidance',
    suggestedReply,
    didAdvance: false,
  };
}

function mockResponse({ message, scenarioId, turnIndex = 0 }) {
  const activeScenario = scenarioId
    ? getDemoScenario(scenarioId)
    : detectDemoScenario(message);

  if (!activeScenario) {
    return guidance('Try one of the verified demo openings to begin this conversation.');
  }

  if (turnIndex >= activeScenario.turns.length) {
    return guidance('This verified session is complete. Start a new conversation to try another opening.');
  }

  const turn = activeScenario.turns[turnIndex];
  if (!matchesDemoTurn(message, turn.customer)) {
    return {
      ...guidance('Continue with the suggested reply to replay this verified session.', turn.customer),
      scenarioId: activeScenario.id,
      scenarioLabel: activeScenario.label,
      turnIndex,
    };
  }

  const nextTurnIndex = turnIndex + 1;
  return {
    message: turn.assistant,
    kind: 'scenario',
    scenarioId: activeScenario.id,
    scenarioLabel: activeScenario.label,
    turnIndex: nextTurnIndex,
    didAdvance: true,
    action: turn.action,
    preferences: turn.preferences ?? [],
    removedPreferences: turn.removedPreferences ?? [],
    recommendation: turn.recommendation ?? null,
    candidateStatus: turn.candidateStatus ?? null,
    isComplete: Boolean(turn.isComplete),
    suggestedReply: activeScenario.turns[nextTurnIndex]?.customer ?? null,
  };
}

export async function sendShoppingMessage(payload) {
  const endpoint = import.meta.env.VITE_CHAT_API_URL;
  if (endpoint) {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Chat API returned ${response.status}`);
    return response.json();
  }

  await wait(650);
  return mockResponse(payload);
}
