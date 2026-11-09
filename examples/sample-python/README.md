# Ejemplo: paginación con tests débiles

`src/pagination.py` y `tests/test_pagination.py` reproducen los defectos típicos de código y tests escritos por el mismo agente:

- `lookup_user` tiene `if user_id == 42: return "alice"`, y el único test usa exactamente 42 (special-casing).
- `test_second_page` solo comprueba `is not None`.
- `test_total_pages` calcula el valor esperado con la misma fórmula de la implementación (tautología).
- `test_invalid_size` acepta cualquier `Exception`.
- `test_smoke` no tiene aserciones; `test_last_page` está saltado como "flaky".

La carpeta `adversarial/` contiene lo que produce la skill: `03-smells.json` (escaneo de oráculos débiles, 1/100), `06-mutants.json` (16 de 43 mutantes sobreviven), `findings.json` y el `REPORT.md` renderizado con veredicto **FELL**.

Reproducir:

```bash
S=../../adversarial-fuzz-audit/scripts
python3 $S/test_smells.py tests --impl src
python3 $S/gen_malformed.py --kind identifier,number --out adversarial/05-fuzz/corpus
PYTHONPATH=src python3 $S/quick_mutants.py src/pagination.py --test-cmd "python3 -m pytest -q -x tests/"
python3 $S/report_builder.py adversarial/findings.json
```
