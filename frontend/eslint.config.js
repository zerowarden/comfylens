import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Branches per function, as ruff's mccabe max-complexity in pyproject.toml.
      complexity: ["warn", 8],
      // The browser never stores or suggests what is typed into the app's fields.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "JSXOpeningElement[name.name=/^(input|textarea)$/]" +
            ":not(:has(JSXAttribute[name.name='autoComplete'][value.value='off']))" +
            ":not(:has(JSXAttribute[name.name='type'][value.value=/^(checkbox|radio|range|file)$/]))",
          message: 'Text fields need autoComplete="off".',
        },
        {
          selector:
            "Literal[value=/\\brounded(-[trblse]{1,2})?-(xs|sm|md|lg|xl|[234]xl)\\b/], " +
            "TemplateElement[value.raw=/\\brounded(-[trblse]{1,2})?-(xs|sm|md|lg|xl|[234]xl)\\b/]",
          message: "Use `rounded`: the app has one corner radius, --radius in index.css.",
        },
      ],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
