import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // catch {} vazio e padrao intencional aqui (ex.: localStorage
      // indisponivel em modo privado) -- so silenciar esse caso, nao bloco
      // vazio em geral.
      'no-empty': ['error', { allowEmptyCatch: true }],
      // eslint-plugin-react-hooks@7 traz o ruleset do React Compiler (muito
      // mais estrito: set-state-in-effect, purity, immutability etc.) junto
      // do 'recommended'. Codebase nunca foi lintado antes -- manter so a
      // regra clássica (rules-of-hooks) como erro bloqueante; as novas regras
      // do compiler entram como warning ate uma limpeza dedicada.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/use-memo': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      'react-hooks/incompatible-library': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/globals': 'warn',
      'react-hooks/refs': 'warn',
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/error-boundaries': 'warn',
      'react-hooks/purity': 'warn',
      'react-hooks/set-state-in-render': 'warn',
      'react-hooks/unsupported-syntax': 'warn',
      'react-hooks/config': 'warn',
      'react-hooks/gating': 'warn',
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // Codebase novo no lint: comeca so com o que pega bug real (regras
      // recommended acima). Variaveis nao usadas viram warning, nao erro,
      // ate uma limpeza dedicada -- ver docs/governanca/decisoes_tecnicas.md.
      '@typescript-eslint/no-unused-vars': 'warn',
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
)
