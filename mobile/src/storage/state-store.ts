import { emptyState, recoverInterrupted, type AppState } from "../domain/model";

export interface Persistence {
  load(): Promise<AppState | null>;
  save(state: AppState): Promise<void>;
}
// Serial writes prevent a slow save from overwriting a newer user action.
// Publish only after durable storage succeeds, so a failed save never appears saved.
export class StateStore {
  state = emptyState();
  private queue: Promise<unknown> = Promise.resolve();
  constructor(
    private persistence: Persistence,
    private publish: (state: AppState) => void = () => {},
  ) {}
  async load() {
    const saved = await this.persistence.load();
    if (saved && (saved.version !== 1 || !Array.isArray(saved.assessments))) {
      throw new Error(
        "Saved preview data could not be read. It has not been reset.",
      );
    }
    const state = recoverInterrupted(saved ?? emptyState());
    await this.persistence.save(state);
    this.state = state;
    this.publish(state);
  }
  update(change: (state: AppState) => AppState): Promise<AppState> {
    const work = this.queue.then(async () => {
      const next = change(this.state);
      await this.persistence.save(next);
      this.state = next;
      this.publish(next);
      return next;
    });
    this.queue = work.catch(() => {});
    return work;
  }
}
