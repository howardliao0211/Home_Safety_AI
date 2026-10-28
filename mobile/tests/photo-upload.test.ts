import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);

// Execute the native upload adapter and Expo's real multipart serializer in Node.
// Only native file/asset access is substituted; URI objects must still fail serialization.
function load(filename: string, dependencies: Record<string, unknown>) {
  const code = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {} as Record<string, any>;
  runInNewContext(code, {
    exports,
    Blob,
    Uint8Array,
    TextEncoder,
    require(name: string) {
      assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
      return dependencies[name];
    },
  });
  return exports;
}

test("native photo uploads serialize file bytes with the SDK 58 fetch serializer", async () => {
  const bytes = new TextEncoder().encode("photo-fixture-bytes");
  class NativeFile {
    constructor(public uri: string) {}
    get name() {
      return "room.jpg";
    }
    get type() {
      return "image/jpeg";
    }
    async bytes() {
      return bytes;
    }
  }
  const adapter = load(resolve("src/api/photo-upload.ts"), {
    "expo-file-system": { File: NativeFile },
    "expo-asset": {
      Asset: {
        fromModule: () => ({
          downloadAsync: async () => ({ localUri: "file:///sample.jpg" }),
        }),
      },
    },
    "../domain/samples": { roomSources: { living: 1 } },
  });
  const expo = dirname(require.resolve("expo/package.json"));
  const serializer = load(
    resolve(expo, "src/winter/fetch/convertFormData.ts"),
    {
      "../../utils/blobUtils": {
        blobToArrayBufferAsync: (blob: Blob) => blob.arrayBuffer(),
      },
    },
  );
  for (const photo of [
    { id: "camera", uri: "file:///camera.jpg" },
    { id: "sample", sample: "living" },
  ]) {
    // RN FormData preserves objects; browser FormData coerces URI objects to strings.
    const parts: [string, unknown][] = [];
    const form = {
      append: (name: string, value: unknown) => parts.push([name, value]),
      entries: () => parts.values(),
    };
    await adapter.appendPhoto(form, photo);
    const { body } = await serializer.convertFormDataAsync(
      form,
      "test-boundary",
    );
    const multipart = new TextDecoder().decode(body);
    assert.match(multipart, /name="photo"; filename="room.jpg"/);
    assert.match(multipart, /content-type: image\/jpeg/);
    assert.ok(multipart.includes("photo-fixture-bytes"));
  }
});
