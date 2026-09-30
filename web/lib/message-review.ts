export interface MessageReviewGateway {
  addMessageToReview(messageId: string): Promise<{ available: boolean }>;
}

export const messageReviewGateway: MessageReviewGateway = {
  async addMessageToReview(_messageId) {
    void _messageId;
    // Review sessions currently require a scheduled concept and generated items.
    return { available: false };
  },
};

export const addMessageToReview = (messageId: string) => messageReviewGateway.addMessageToReview(messageId);
