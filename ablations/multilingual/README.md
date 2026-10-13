# Request-language ablation (Table 3)

Does a coding agent do worse when the user writes in another language? Sec. 4.2 of the paper
translates the ten requests of every EvoWeb app into French, German, Chinese, Hindi and Hebrew,
keeps the application itself in
English, and re-runs Sonnet 4.6 and Haiku 4.5 with everything else unchanged.

| What | Where |
|---|---|
| datasets | the `multilingual` config of [the HF dataset](https://huggingface.co/datasets/TD-Labs/EvoWeb) (splits `fr de zh hi he`): translated request text, an explicit English-UI mandate in request 1, every feature / page / button referred to by its exact English name inside the foreign sentence, and the **untouched English judge tasks** (identical to the English benchmark) |
| runs | `evoweb.arms.MULTILINGUAL`: one full 32-app run per (model, language), `multilingual-sonnet-4.6-<lang>` and `multilingual-haiku-4.5-<lang>` in the released traces |
| scoring | `ablations/multilingual/score_arms.py` |

```bash
python3 ablations/multilingual/score_arms.py                  # both models
python3 ablations/multilingual/score_arms.py "Sonnet 4.6"     # one model
python3 ablations/multilingual/score_arms.py --json out.json  # also write every arm's metrics
```

Output, per model: raw accuracy, norm, Grade (norm-sweep AUC / 100) and Survival (requests-survived
AUC) for English (the model's Table 2 row, the mean of its three runs) and each of the five
languages, one run each. Grade is
the number Table 3 prints.

## Why "English UI"

An earlier variant had the translated user ask for a website *in* the target language, so the
generated UI was Hebrew, Chinese, ... and the judge tasks had to be edited to point at translated
labels. Its penalties turned out to be mostly judge-side: once the judge sees an English UI they
disappear. The paper therefore reports the English-UI variant, where the only thing that changes
across arms is the language the instruction is written in. The translated-UI runs are not
released.
