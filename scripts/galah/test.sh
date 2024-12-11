#!/bin/bash

python3 download.py --tiny

cd data/spectra

../../prepare.sh

cd ../..

python3 build_parent_sample.py --data_dir data/spectra/spectra --allstar_file data/GALAH_DR3_main_allstar_v2.fits --resolution_map_dir data --vac_file data/GALAH_DR3_VAC_ages_v2.fits  --missing_id_file data/GALAH_DR3_list_missing_reduced_spectra_v2.csv --output_dir ./dr3 --nside 16 --num_workers 4 --tiny

python3 test_load.py
