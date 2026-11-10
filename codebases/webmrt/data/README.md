# Sample data

`sample_RF_Data.csv` is a 451-row subsample (21%) of the 2,159-row WebMRT training table `RF_Data.csv`.
The table holds MaRTy field measurements of mean radiant temperature in Phoenix-Tempe, Arizona, collected between
2016-07-12 and 2019-07-15, with sky/tree/building/pervious fractions, shade, detrended air temperature and solar
geometry. The first column (`Unnamed: 0`) is the original row number.

**How it was made** (`python -m webmrt.sampling RF_Data.csv`): seed 42; stratified by `Shade_AtMeasurement`
(0/1/2) x solar-altitude tercile; the two rows holding the minimum and maximum of `surr_pervious` are always kept,
so the min-max normalisation of that column is identical to the full table.

**Status:** included for demonstration in this open-source release (code: Apache-2.0, see `../LICENSE`).
Columns used by the model: `SVF_Up, surr_trees, surr_buildings, surr_pervious, Shade_AtMeasurement,
AirT_C_detrended, Solar_Altitude, min_from_sunrise` (target: `MRT_C_detrended`).
