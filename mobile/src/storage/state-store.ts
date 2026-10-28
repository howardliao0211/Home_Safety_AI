import { emptyState, recoverInterrupted, type AppState } from "../domain/model";

export interface Persistence {
  load(): Promise<AppState | null>;
  save(state: AppState): Promise<void>;
}
// Serial writes prevent a slow save from overwriting a newer user action.
// Publish only after durable storage succeeds, so a failed save never appears saved.
export class StateStore {
  state = emptyState();
  private disposed = false;
  dispose() {
    this.disposed = true;
  }
  async drained() {
    await this.queue;
  }
  private check() {
    if (this.disposed) throw new Error("The account session has changed.");
  }
  private queue: Promise<unknown> = Promise.resolve();
  constructor(
    private persistence: Persistence,
    private publish: (state: AppState) => void = () => {},
  ) {}
  async load() {
    this.check();
    const saved = await this.persistence.load();
    if (saved && (saved.version !== 1 || !Array.isArray(saved.assessments))) {
      throw new Error(
        "Saved preview data could not be read. It has not been reset.",
      );
    }
    const state = recoverInterrupted(saved ?? emptyState());
    this.check();
    await this.persistence.save(state);
    this.check();
    this.state = state;
    this.publish(state);
  }
  update(change: (state: AppState) => AppState): Promise<AppState> {
    const work = this.queue.then(async () => {
      this.check();
      const next = change(this.state);
      await this.persistence.save(next);
      this.check();
      this.state = next;
      this.publish(next);
      return next;
    });
    this.queue = work.catch(() => {});
    return work;
  }
}
