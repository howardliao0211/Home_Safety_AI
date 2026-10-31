import { expect, test } from "@playwright/test";
import { build } from "esbuild";
import path from "node:path";

// Exercise the real gate while navigation is still mounted after cache removal.
// A load of the deleted ID models the service's 404 and shared error notice.
let harness: string;
test.beforeAll(async () => {
  const result = await build({
    stdin: {
      contents: `
        import React, { useState } from "react";
        import { createRoot } from "react-dom/client";
        import { AssessmentGate } from "./src/components/assessment-gate";
        import { Context } from "@/hooks/preview-context";
        function Harness() {
          const query = new URLSearchParams(location.search);
          const [assessments, setAssessments] = useState(query.has("missing") ? [] : [{ id: "saved" }]);
          const [error, setError] = useState("");
          const [reads, setReads] = useState(0);
          return <Context.Provider value={{
            state: { assessments }, error,
            loadAssessment: async (id) => {
              setReads(n => n + 1);
              if (query.has("hydrate")) {
                setAssessments([{ id }]);
                return { id };
              }
              setError("Assessment not found.");
            },
          }}>
            <output data-testid="reads">{reads}</output>
            <AssessmentGate id="saved">
              <h1>Saved assessment</h1>
              <button onClick={() => setAssessments([])}>Complete deletion</button>
            </AssessmentGate>
          </Context.Provider>;
        }
        createRoot(document.getElementById("root")).render(<Harness />);
      `,
      resolveDir: process.cwd(),
      loader: "tsx",
    },
    bundle: true,
    write: false,
    jsx: "automatic",
    plugins: [
      {
        name: "gate-environment",
        setup(builder) {
          builder.onResolve(
            {
              filter:
                /^(@\/hooks\/preview-context|\.\/ui|expo-router|react-native)$/,
            },
            (args) => ({ path: args.path, namespace: "gate-mock" }),
          );
          builder.onLoad({ filter: /.*/, namespace: "gate-mock" }, (args) => ({
            loader: "tsx",
            resolveDir: process.cwd(),
            contents:
              args.path === "@/hooks/preview-context"
                ? 'import React from "react"; export const Context = React.createContext(null); export const usePreview = () => React.useContext(Context);'
                : args.path === "./ui"
                  ? `import React from "react"; import { usePreview } from "@/hooks/preview-context";
                export function Screen({children}) { const {error} = usePreview(); return <main>{error && <p>This change could not be completed. {error}</p>}{children}</main>; }
                export const Copy = ({children}) => <div>{children}</div>;
                export const Button = ({label,onPress}) => <button onClick={onPress}>{label}</button>;`
                  : args.path === "expo-router"
                    ? 'import React from "react"; export const Redirect = () => <main>Returned Home</main>; export const router = { dismissTo() {} };'
                    : 'import React from "react"; export const ActivityIndicator = () => <div>Loading</div>;',
          }));
          builder.onResolve({ filter: /^@\/components\/theme$/ }, () => ({
            path: path.resolve("src/components/theme.ts"),
          }));
        },
      },
    ],
  });
  harness = result.outputFiles[0].text;
});

test.beforeEach(async ({ page }) => {
  await page.route("**/__gate-test**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<div id="root"></div><script>${harness}</script>`,
    }),
  );
});

test("deleted assessment is not reloaded or reported as a failed change", async ({
  page,
}) => {
  await page.goto("/__gate-test");
  await page.getByRole("button", { name: "Complete deletion" }).click();
  await expect(page.getByText("Returned Home", { exact: true })).toBeVisible();
  await expect(page.getByTestId("reads")).toHaveText("0");
  await expect(
    page.getByText(/This change could not be completed/),
  ).toHaveCount(0);
});

test("uncached assessment still hydrates on direct entry", async ({ page }) => {
  await page.goto("/__gate-test?missing&hydrate");
  await expect(
    page.getByRole("heading", { name: "Saved assessment" }),
  ).toBeVisible();
  await expect(page.getByTestId("reads")).toHaveText("1");
});

test("unavailable direct entry still offers retry", async ({ page }) => {
  await page.goto("/__gate-test?missing");
  await page.getByRole("button", { name: "Retry opening assessment" }).click();
  await expect(page.getByTestId("reads")).toHaveText("2");
  await expect(
    page.getByText("Assessment unavailable", { exact: true }),
  ).toBeVisible();
});
