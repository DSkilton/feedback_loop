class FeedbackDraftStore {
  constructor() {
    this.connection = null;
  }

  async open() {
    if (!this.connection) {
      this.connection = new Promise((resolve, reject) => {
        if (!("indexedDB" in window)) return reject(new Error("This browser does not support offline drafts."));
        const request = indexedDB.open("feedback-loop-drafts-v1", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("drafts", { keyPath: "key" });
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("Cannot access local draft storage."));
        request.onblocked = () => reject(new Error("Close other Feedback Loop tabs before updating draft storage."));
      }).catch((error) => {
        this.connection = null;
        throw error;
      });
    }
    return this.connection;
  }

  async execute(mode, operation) {
    const database = await this.open();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction("drafts", mode);
      const store = transaction.objectStore("drafts");
      const request = operation(store);
      let result;
      request.onsuccess = () => { result = request.result; };
      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(transaction.error || new Error("Local draft write failed."));
      transaction.onabort = () => reject(transaction.error || new Error("Local draft write was cancelled."));
    });
  }

  get(key) {
    return this.execute("readonly", (store) => store.get(key));
  }

  put(draft) {
    return this.execute("readwrite", (store) => store.put(draft));
  }

  remove(key) {
    return this.execute("readwrite", (store) => store.delete(key));
  }

  async list(prefix) {
    const all = await this.execute("readonly", (store) => store.getAll());
    return all.filter((item) => item.key.startsWith(prefix));
  }
}

window.feedbackDraftStore = new FeedbackDraftStore();
