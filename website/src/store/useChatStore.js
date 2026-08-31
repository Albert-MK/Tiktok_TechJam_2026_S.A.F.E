import { create } from 'zustand';
import { sendShoppingMessage } from '../services/chatApi';

const createMessage = (role, text, metadata = {}) => ({
  id: crypto.randomUUID(),
  role,
  text,
  ...metadata,
});

export const useChatStore = create((set, get) => ({
  messages: [],
  isLoading: false,
  error: null,
  requestId: 0,
  scenarioId: null,
  scenarioLabel: null,
  turnIndex: 0,
  isComplete: false,

  send: async (text) => {
    const message = text.trim();
    if (!message || get().isLoading) return;

    const history = get().messages;
    const requestId = get().requestId + 1;
    set((state) => ({
      messages: [...state.messages, createMessage('user', message)],
      isLoading: true,
      error: null,
      requestId,
    }));

    try {
      const result = await sendShoppingMessage({
        message,
        history,
        scenarioId: get().scenarioId,
        turnIndex: get().turnIndex,
      });
      if (get().requestId !== requestId) return;
      set((state) => ({
        messages: [...state.messages, createMessage('assistant', result.message, {
          kind: result.kind,
          action: result.action,
          preferences: result.preferences,
          removedPreferences: result.removedPreferences,
          recommendation: result.recommendation,
          candidateStatus: result.candidateStatus,
          suggestedReply: result.suggestedReply,
          isComplete: result.isComplete,
        })],
        isLoading: false,
        scenarioId: result.scenarioId ?? state.scenarioId,
        scenarioLabel: result.scenarioLabel ?? state.scenarioLabel,
        turnIndex: result.didAdvance ? result.turnIndex : state.turnIndex,
        isComplete: result.isComplete ?? state.isComplete,
      }));
    } catch (error) {
      if (get().requestId !== requestId) return;
      set({ isLoading: false, error: error.message || 'Something went wrong. Please try again.' });
    }
  },

  reset: () => set((state) => ({
    messages: [],
    isLoading: false,
    error: null,
    requestId: state.requestId + 1,
    scenarioId: null,
    scenarioLabel: null,
    turnIndex: 0,
    isComplete: false,
  })),
}));
