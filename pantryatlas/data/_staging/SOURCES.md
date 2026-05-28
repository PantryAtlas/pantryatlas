# Raw vocab sources (T-007 staging)

recipenlg_url: https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00000-of-00004-237b1b1141fdcfa1.parquet
recipenlg_sha256: 7682976c0416a5f91d65b0db5a821d25b4f59f055523db656f081174663a9778
recipenlg_rows: 2147248
recipenlg_note: All four corbt/all-recipes shards concatenated (shard URLs listed below).
recipenlg_shards:
  - https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00000-of-00004-237b1b1141fdcfa1.parquet
  - https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00001-of-00004-d46654ac93566129.parquet
  - https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00002-of-00004-3b4f78b99eedadc2.parquet
  - https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00003-of-00004-2369b90eb0860a76.parquet

flavordb_url: https://cosylab.iiitd.edu.in/flavordb/entities_json?id={id}
flavordb_sha256: 1bd19a55a813f65d713c31c961d5c02ee1093ddfc3452df4479b3b2892f25bbe
flavordb_rows: 935
flavordb_note: Scraped from live FlavorDB API, entity IDs 1..1000.

## License

- **RecipeNLG / corbt/all-recipes**: The `corbt/all-recipes` dataset on HuggingFace Hub is a
  community mirror of the RecipeNLG corpus (Bien et al., 2020). The upstream RecipeNLG dataset
  is distributed under **CC-BY-NC-4.0** (Creative Commons Attribution-NonCommercial 4.0
  International). Non-commercial use only; attribution required.
  Original dataset: https://recipenlg.cs.put.poznan.pl/
  Mirror used: https://huggingface.co/datasets/corbt/all-recipes

- **FlavorDB**: FlavorDB (Garg et al., 2018) is provided by the Computational Biology Group,
  IIIT Delhi. It is distributed under the **Creative Commons Attribution-NonCommercial-ShareAlike
  3.0 Unported (CC BY-NC-SA 3.0)** license. Non-commercial use only; attribution required;
  derivatives must share under the same license.
  Source: https://cosylab.iiitd.edu.in/flavordb/
  Paper: https://academic.oup.com/nar/article/doi/10.1093/nar/gkx957/4559748

## Redistribution note

Both datasets are used for derived vocabulary aggregation only. The final
`ingredients.parquet` (T-008 output) does not redistribute recipe text or flavor-compound
relationships — only canonical ingredient name strings extracted from these sources.

The raw parquet files in this `_staging/` directory are **gitignored** and must not be
committed or distributed. Only `SOURCES.md` (this file) is committed to the repository.
