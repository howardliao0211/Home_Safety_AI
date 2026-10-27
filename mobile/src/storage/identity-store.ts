export class IdentityStore {
  private pending?: Promise<string>;
  constructor(
    private read: () => Promise<string | null>,
    private write: (id: string) => Promise<void>,
    private generate: () => string,
  ) {}
  get(): Promise<string> {
    if (!this.pending) {
      this.pending = (async () => {
        const existing = await this.read();
        if (existing) {
          if (
            !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
              existing,
            )
          )
            throw new Error(
              "The saved device identity is invalid. It has not been replaced.",
            );
          return existing;
        }
        const id = this.generate();
        await this.write(id);
        return id;
      })().catch((error) => {
        this.pending = undefined;
        throw error;
      });
    }
    return this.pending;
  }
}
