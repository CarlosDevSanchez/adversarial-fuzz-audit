# adversarial-fuzz-audit

> **Nota de idioma:** este README está en español. La skill (`SKILL.md`, referencias, prompts y scripts) está escrita **en inglés** a propósito: los modelos consumen menos tokens leyendo inglés y las instrucciones se siguen con más fidelidad. Lo que lee el agente va en inglés; lo que lee la persona, aquí, va en español.

Skill para **Claude Code** (y compatible con cualquier agente que lea `SKILL.md`) que somete el código escrito por un agente de IA a una **verificación adversarial independiente**: otro modelo, que no escribió el código ni sus tests, intenta romperlo con tests adversariales, fuzzing con datos malformados, propiedades, relaciones metamórficas y mutation testing, y entrega un informe que dice si la afirmación "funciona, todos los tests pasan" se sostiene o cae.

---

## El problema que resuelve

Cuando Claude, Codex, Gemini o cualquier agente escribe el código **y también** sus tests, está calificando su propia tarea. Los tests heredan los mismos puntos ciegos que el código, afirman lo que la implementación ya hace en lugar de lo que la especificación exige, y el agente tiene un incentivo claro para que todo salga en verde. No es una sospecha: hay evidencia.

- Los estudios sobre tests generados por LLM identifican la **debilidad del oráculo** (aserciones triviales, valores esperados copiados de una ejecución, aserciones que repiten la lógica de la implementación) como la limitación principal, no la cobertura (Celik y Mahmoud, GEM; Ouédraogo et al., arXiv 2410.10628).
- Los modelos muestran **sesgo de autopreferencia** al evaluar su propia salida (Laurito et al., PNAS 2025; Chen et al., arXiv 2504.03846). Una sesión nueva del mismo modelo borra la memoria, no el sesgo.
- Benchmarks de 2025 diseñados para medirlo (**ImpossibleBench**, **EvilGenie**, **GSO HackDetector**) observaron a Codex y a Claude Code editando tests, codificando casos especiales para el input exacto del test y falseando resultados para que la suite pasara.

Conclusión: **una suite verde escrita por el autor es una afirmación, no una evidencia.** Esta skill convierte esa afirmación en algo falsable.

## Conceptos clave en los que se apoya

| Concepto | Qué aporta a la skill |
|---|---|
| **Separación de funciones (autor ≠ adversario)** | Quien escribió el código o los tests nunca los audita. "Otro modelo" significa otra familia o proveedor (Anthropic, OpenAI, Google, otros), no una sesión nueva del mismo. |
| **Especificación antes que implementación** | El adversario deriva las propiedades esperadas de la spec a ciegas, y solo después lee el código y los tests para buscar lo que dejaron fuera. Evita anclarse en las suposiciones del autor. |
| **Problema del oráculo** (Weyuker 1982; Barr et al. 2015) | Un fuzzer solo detecta crashes. La skill lo combina con oráculos fuertes: propiedades, relaciones metamórficas y pseudo-oráculos diferenciales. |
| **Fuzzing por capas** | Corpus malformado determinista → property-based testing con shrinking → fuzzing guiado por cobertura (Atheris, Jazzer, cargo-fuzz, `go test -fuzz`, libFuzzer, AFL++), siempre en sandbox y con presupuesto de tiempo. |
| **Mutation testing** | La prueba más contundente de que una suite es débil: inyectar bugs y ver que los tests siguen en verde. Cada mutante superviviente es un bug concreto que la suite dejaría pasar. |
| **Ley de Goodhart** | Cobertura, número de tests y CI en verde son métricas que se vuelven objetivos. La skill prefiere evidencia difícil de optimizar: mutantes supervivientes, contraejemplos mínimos, crashes reproducibles. |
| **Romper, no arreglar** | El adversario nunca edita el código ni los tests del autor. Si arregla, vuelve a ser autor y destruye la evidencia. Documenta, reproduce, informa y devuelve. |
| **Alcance honesto** | Cero hallazgos significa "no se rompió dentro de este presupuesto", nunca "es correcto". El informe dice qué se atacó, con qué, cuánto tiempo, y qué no. |

## Cómo decide quién es el adversario

La skill primero establece la **procedencia** (quién escribió el código y quién los tests) leyendo trailers de git (`Co-Authored-By: Claude`, `Co-authored-by: Codex`, `Claude-Session:`, bots de Copilot, Gemini, Aider, Cursor, Devin…) o preguntando al usuario. Después detecta qué agentes y claves de API hay disponibles (`claude`, `codex`, `gemini`, `opencode`, `aider`, `copilot`, etc.) y aplica la tabla de enrutamiento:

| Autor del código | Autor de los tests | El adversario debe ser |
|---|---|---|
| Modelo A | Modelo A | Cualquier modelo distinto de A (preferible otro proveedor) |
| Modelo A | Modelo B | Un modelo distinto de B (A es aceptable; un tercero es mejor) |
| Humano | Modelo A | Distinto de A |
| Modelo A | Humano | Distinto de A; los tests humanos también se auditan |
| Nadie todavía (la skill escribe los tests) | Nosotros (modelo X) | Distinto de X. Escribimos los tests y otro modelo ataca el código **y nuestros tests** |
| Cualquiera | Cualquiera, pero no hay otro modelo | **Se detiene y pregunta.** Solo continúa con el mismo modelo si el usuario lo decide explícitamente, y el informe lleva una advertencia visible de independencia |

El punto más importante: **ejecutar todo con el mismo modelo y el mismo agente es siempre una decisión explícita del usuario**, nunca un atajo que la skill toma por su cuenta. El script `run_adversary.sh` se niega a ejecutarse cuando el proveedor del adversario coincide con el del autor, salvo que se pase `--allow-same-model`, y ese override queda registrado en el informe.

Si la skill misma tiene que escribir los tests (porque no existen), lo declara, los escribe con disciplina de autor (valores esperados derivados a mano de la spec, nunca ejecutando la implementación) y luego enruta a **otro modelo** para que ataque tanto el código como esos tests. Dar por buenos nuestros propios tests corrompería el concepto.

## Las 8 fases del flujo

| Fase | Objetivo | Artefacto |
|---|---|---|
| 0. Intake | Fijar la afirmación que se ataca, la superficie, la spec y el presupuesto | `adversarial/00-intake.md` |
| 1. Procedencia | Quién escribió el código y quién los tests | `adversarial/01-provenance.json` |
| 2. Enrutamiento del adversario | Elegir un modelo que no sea el autor | `adversarial/02-routing.json` |
| 3. Auditoría de la afirmación | Medir la fuerza del oráculo de los tests existentes (smells, índice de tautología) | `adversarial/03-claim-audit.md` |
| 4. Plan de ataque | Pasada ciega desde la spec, luego pasada informada leyendo código y tests | `adversarial/04-attack-plan.md` |
| 5. Campaña de fuzzing | Corpus malformado, property-based, fuzzing guiado por cobertura | `adversarial/05-fuzz/` |
| 6. Chequeo de mutantes | Probar si la suite detecta bugs inyectados | `adversarial/06-mutants.json` |
| 7. Triaje | Reproducir, minimizar, deduplicar, clasificar, atribuir | `adversarial/findings.json` |
| 8. Informe | Veredicto `HELD` / `PARTIALLY HELD` / `FELL` con evidencia | `adversarial/REPORT.md` |

Todo lo que produce la skill vive en `adversarial/`. El código y los tests del autor se tratan como solo lectura.

## Estructura del repositorio

```
adversarial-fuzz-audit/
├── README.md                      ← este archivo (español)
├── LICENSE                        ← MIT
├── dist/
│   └── adversarial-fuzz-audit.skill   ← paquete listo para importar
├── examples/
│   └── sample-python/             ← proyecto de ejemplo con tests débiles + informe generado
└── adversarial-fuzz-audit/        ← LA SKILL (en inglés)
    ├── SKILL.md                   ← flujo de 8 fases, principios, reglas de combate
    ├── references/
    │   ├── principles.md          ← el porqué, con fuentes
    │   ├── provenance.md          ← huellas de agentes en git, matriz de responsabilidad
    │   ├── adversary-routing.md   ← detección, tabla de enrutamiento, comandos por CLI, protocolo de override
    │   ├── test-smells.md         ← catálogo de 17 oráculos débiles con heurísticas de detección
    │   ├── attack-playbook.md     ← 14 clases de ataque con payloads concretos
    │   ├── fuzzing.md             ← estrategias, matriz de herramientas por lenguaje, harnesses, sandbox, triaje
    │   ├── property-metamorphic.md← cómo derivar propiedades y relaciones metamórficas; cheat sheets
    │   ├── mutation-testing.md    ← herramientas, lectura de supervivientes, mutantes equivalentes
    │   └── report-format.md       ← rúbrica de severidad, reglas de veredicto, guía del template
    ├── scripts/                   ← solo biblioteca estándar (Python 3.9+, bash)
    │   ├── detect_agents.py       ← qué CLIs de agentes y claves de API hay; qué modelo corre la sesión
    │   ├── provenance.py          ← matriz de autoría código/tests desde git
    │   ├── run_adversary.sh       ← invoca a otro modelo con el prompt adversarial; guardia de independencia
    │   ├── test_smells.py         ← escaneo heurístico de oráculos débiles (Python, JS/TS, Go, Java, Rust, C#, Ruby, PHP)
    │   ├── gen_malformed.py       ← corpus determinista de ~780 inputs hostiles (strings, números, JSON, bytes, CSV, URL, paths, fechas, IDs)
    │   ├── quick_mutants.py       ← mutation testing sin dependencias para Python (AST)
    │   └── report_builder.py      ← valida findings.json y renderiza REPORT.md
    └── assets/
        ├── prompts/adversary_prompt.md   ← el prompt que recibe el modelo adversario
        ├── prompts/author_prompt.md      ← disciplina cuando la skill escribe los tests
        ├── findings_schema.json          ← esquema del JSON de hallazgos
        └── report_template.md            ← plantilla del informe final
```

## Instalación

**Opción A: archivo `.skill`** (Claude.ai / Claude Code con soporte de skills)
Descarga `dist/adversarial-fuzz-audit.skill` e impórtalo desde la configuración de skills, o usa el botón **Save skill** cuando Claude te lo presente.

**Opción B: carpeta en el proyecto** (Claude Code)
```bash
git clone https://github.com/CarlosDevSanchez/adversarial-fuzz-audit.git
mkdir -p .claude/skills
cp -r adversarial-fuzz-audit/adversarial-fuzz-audit .claude/skills/
```

**Opción C: carpeta global**
```bash
cp -r adversarial-fuzz-audit/adversarial-fuzz-audit ~/.claude/skills/
```

Los scripts no necesitan dependencias extra. Para property-based testing y fuzzing guiado por cobertura la skill usa la librería del proyecto (Hypothesis, fast-check, proptest, rapid, jqwik, Atheris, Jazzer, cargo-fuzz…); las instala solo dentro de `adversarial/` y nunca toca el manifiesto del proyecto sin preguntar.

## Uso

La skill se activa cuando le pides a Claude verificar, retar, romper, fuzzear o auditar código que escribió un agente, o cuando desconfías de tests que un agente escribió para su propio código. Ejemplos de peticiones:

- "Codex implementó el parser de CSV y dice que todo pasa. Rómpelo."
- "Haz un fuzzing adversarial al endpoint de paginación que generó Claude ayer; los tests los escribió él mismo."
- "No hay tests. Escríbelos y luego que otro modelo intente tirarlos."
- "Audita esta suite: sospecho que solo prueba el camino feliz."

Si quieres forzar la skill: `/adversarial-fuzz-audit`.

### Uso manual de los scripts

```bash
S=.claude/skills/adversarial-fuzz-audit/scripts

python3 $S/detect_agents.py --table                      # qué adversarios hay disponibles
python3 $S/provenance.py . src tests --json adversarial/01-provenance.json
python3 $S/test_smells.py tests --impl src --json adversarial/03-smells.json
python3 $S/gen_malformed.py --kind all --out adversarial/05-fuzz/corpus
python3 $S/quick_mutants.py src/modulo.py --test-cmd "python3 -m pytest -q -x tests/" --json adversarial/06-mutants.json
$S/run_adversary.sh --agent codex --author anthropic --target src/modulo.py --spec adversarial/00-intake.md
# opcional: aislar al adversario con ADVERSARY_WRAPPER (contenedor con salida limitada a la API del proveedor)
ADVERSARY_WRAPPER="docker run --rm -v $PWD:/w -w /w -e ANTHROPIC_API_KEY img" $S/run_adversary.sh --agent codex --author anthropic --target src/modulo.py
python3 $S/report_builder.py adversarial/findings.json --out adversarial/REPORT.md
# --verify re-ejecuta cada reproduction.command (debe salir con código != 0 mientras el defecto exista)
python3 $S/report_builder.py adversarial/findings.json --verify
```

## Ejemplo

`examples/sample-python/` contiene un módulo de paginación con los defectos típicos de un agente (un `if user_id == 42: return "alice"` que existe solo para satisfacer un test, un `pytest.raises(Exception)`, un test sin aserciones, un test saltado como "flaky", un valor esperado calculado con la misma fórmula de la implementación) y el `REPORT.md` que la skill produce. El escaneo de smells puntúa la suite 1/100, el mutation check deja vivos 16 de 43 mutantes, y el veredicto es **FELL**.

## Qué NO hace esta skill

- No arregla el código. Devuelve una lista de pendientes al autor; el autor arregla y, si se pide, el adversario vuelve a atacar en una nueva ronda.
- No fuzzea servicios en producción ni APIs de terceros. Solo código propio, en sandbox, con límites de recursos.
- No promete corrección. Un veredicto `HELD` significa "no se pudo falsar dentro del alcance y el presupuesto declarados".
- No ejecuta al autor como adversario por su cuenta. Esa decisión es siempre del usuario y queda registrada.

## Limitaciones y modelo de amenazas

- La procedencia desde git es una heurística, no una prueba de quién escribió qué.
- La independencia del adversario se basa en el agente/modelo declarado, no en una prueba criptográfica (`unverified-provider` para CLIs multi-proveedor sin `--model`).
- El código objetivo y la especificación se envían al proveedor elegido: no usar con código que no puedas compartir; deja secretos como `.env` fuera del árbol o del alcance.
- Los comandos de test y fuzzing se ejecutan con los permisos del usuario y están pensados para código propio. Para árboles no confiables, usa `ADVERSARY_WRAPPER` con un contenedor cuya salida de red se limite a la API del proveedor (sin red solo para modelos locales) y con las credenciales pasadas al contenedor. `--verify` ejecuta en el host los `reproduction.command` escritos por el adversario: revísalos antes.
- Los generadores de corpus no son motores de fuzzing; el arnés lo construye el agente.
- La comprobación de integridad posterior a la ejecución detecta, pero no impide, ediciones fuera de `adversarial/`. `gemini`, `copilot` y `aider` aprueban herramientas automáticamente: preferir codex o un wrapper.

**Cambios en 1.1.0:** `quick_mutants.py` ya no cuenta los timeouts dentro de `killed`; usa `detected` (= killed + timeout) para la puntuación.

**Cambios en 1.1.1:** el filtro de integridad ya no oculta `.coveragerc` y acepta `--out` absoluto dentro del repo; `run_adversary.sh` documenta 124/142 (presupuesto excedido); el finding F-02 del ejemplo es ahora un guard redundante (mutante equivalente), no una falta de test.

## Fuentes principales

- Chen et al., *Do LLM Evaluators Prefer Themselves for a Reason?*, arXiv 2504.03846 (2025)
- Laurito et al., self-preference in LLM judgments, PNAS (2025)
- Ouédraogo et al., *Test smells in LLM-generated unit tests*, arXiv 2410.10628
- Celik y Mahmoud, *GEM: mutation-guided assertion strengthening*
- ImpossibleBench (2025); EvilGenie, MIT FutureTech (2025); GSO HackDetector (2025)
- Barr, Harman, McMinn, Shahbaz, Yoo, *The Oracle Problem in Software Testing: A Survey*, IEEE TSE 2015; Weyuker, *On Testing Non-Testable Programs*, 1982
- Hypothesis, fast-check, proptest, Atheris, Jazzer, cargo-fuzz, mutmut, Stryker, PIT, cargo-mutants: documentación oficial de cada proyecto

## Licencia

MIT. Úsala, modifícala y compártela. Si la mejoras, un pull request es bienvenido.
