import argparse
from concurrent.futures import ThreadPoolExecutor
import functools
import os
from pathlib import Path

from filelock import FileLock
from astropy.io import fits
from astropy.wcs import WCS
from astroquery.mast import Observations
import h5py
import healpy as hp
import numpy as np
import pandas as pd

import cutout_utils

"""
Example usage:
    python -m cosmos_tiles_script --metadata_path=/path/to/metadata_main.csv \
        --morphology_path=/path/to/gz_hubble_main.csv \
        --downloads_folder=/path/to/COSMOS --pid_list=1,2 \
        --target_name_paths=/path/to/targets_1.npy,/path/to/targets_2.npy \
        --nan_tolerance=0.99 --zero_tolerance=0.99
"""

# COSMOS query params
# HST proposal IDs for targets
PID_LIST = [9822,10092]
# paths to npy files containing a list of targets for each proposal id
TARGET_FILES = ['pid9822_targets.npy','pid10092_targets.npy'] 

# properties of our HST images
PIXEL_SCALE = 0.05 # HST drizzled pixel scale in arcseconds
NUMPIX = 100
CUTOUT_SIZE = NUMPIX * PIXEL_SCALE # approx 100 pixel cutouts.
PIDS = ['10092', '9822']
HEALPIX_NSIDE = 16
NUM_EXPOSURES = 4 # number of exposures added together by drizzle.
DARK_CURRENT = 0.0168 # e-/s/pixel,from exposure time calculator

class CosmosCutouts():
    """
    Class for generating cutouts from the COSMOS field.

    Args:
        metadata_main_path (string): path to .csv containing galaxy zoo
            source catalog. Downloaded from
            https://data.galaxyzoo.org/#section-11.
        morphology_path (string): path to .csv containing galaxy zoo
            morphological classifications
        downloads_folder (string): where to store .fits files downloaded
            from MAST
        nan_tolerance (float): What fraction of the cutout is allowed to be
            a nan. If 1.0, all values can be nans.
        zero_tolerance (float): What fraction of the cutout is allowed to be
            zero. If 1.0 all values can be zeros.
    """

    def __init__(
        self, metadata_main_path, morphology_path, downloads_folder,
        output_dir,nan_tolerance=1.0, zero_tolerance=1.0
    ):
        # set properties
        self.downloads_folder = downloads_folder
        self.nan_tolerance = nan_tolerance
        self.zero_tolerance = zero_tolerance
        self.output_dir = output_dir

        # load galaxy-zoo metadata
        metadata_main_df = pd.read_csv(metadata_main_path, low_memory=False)
        cosmos_df = metadata_main_df[metadata_main_df['imaging'] == 'COSMOS']

        # read in morphology classifications
        morph_df = pd.read_csv(morphology_path, low_memory=False)
        # set index to zooniverse ID, index in order of cosmos_df zooniverse
        # IDs, then reset index
        morph_df = (
            morph_df.set_index('zooniverse_id').loc[
                cosmos_df['zooniverse_id']
            ].reset_index()
        )
        # add in relevant morphology parameters from morph_df
        cosmos_df = cosmos_df.merge(
            morph_df, on='zooniverse_id', how='left', suffixes=(None, '_gz')
        )

        # remove rows that are flagged as an artifact & save to object
        self.cosmos_df = (
            cosmos_df[cosmos_df[
                't01_smooth_or_features_a03_star_or_artifact_flag'
            ] == False]
        )

    def make_cutouts(
        self, targets_df, flux_tile, weight_tile, wcs_tile, print_status=True
    ):
        """
        Args:
            targets_df (pd.dataframe): contains 'RA' 'DEC' for targets
            flux_tile (np.array[float], size=(npix,npix)): image for full tile.
            weight_tile (np.array[float], size=(npix,npix)): weight for full
                tile.
            wcs_tile (astropy.wcs.WCS): wcs of the image / weights tile.
            print_status (bool): If true will print the success rate.
        Returns:
            (np.array, np.array, np.array): The flux, weights, and indices for
                each galaxy in the DataFrame.
        """
        # keep track of skips.
        target_idxs = targets_df.index.to_list()
        num_objects = len(target_idxs)

        # loop through targets & create the cutout
        results = map(
            functools.partial(
                cutout_utils.make_cutout_single, targets_df=targets_df,
                flux_tile=flux_tile, weight_tile=weight_tile,
                wcs_tile=wcs_tile, nan_tolerance=self.nan_tolerance,
                zero_tolerance=self.zero_tolerance, cutout_size=CUTOUT_SIZE,
                dark_current=DARK_CURRENT,num_exposures=NUM_EXPOSURES
            ),
            target_idxs
        )

        # remove the skips.
        results = [res for res in results if res is not None]
        flux_maps, ivar_maps, idx = (
            map(list, zip(*results)) if results else ([], [], [])
        )

        if print_status:
            print(
                f'Generated cutouts with a success rate of '
                f'{len(flux_maps) / num_objects}'
            )

        return flux_maps, ivar_maps, idx

    @staticmethod
    def _extract_numpy(df_column):
        """
        Helper function for dealing with masking in pandas to hdf5.

        Args:
            df_column (pd.DataFrame): Dataframe column to be convereted to numpy.

        Returns:
            Numpy array with NaN values properly dealt with.
        """
        if df_column.dtype.kind in {'f', 'i'}:  # Numeric columns use np.nan.
            return df_column.fillna(np.nan).to_numpy()
        else:  # For non-numeric columns, return NaN string.
            return df_column.fillna("NaN").to_numpy()


    def _save_cutouts(
        self, save_dir, flux_cutouts, ivar_cutouts, cutouts_df
    ):
        """
        Save the cutouts to disk.

        Args:
            save_dir (string): where .h5 files are stored
            flux_cutouts (np.array, size=(n_galaxies,npix,npix)): Flux of each
                cutout.
            ivar_cutouts (np.array, size=(n_galaxies,npix,npix)): Inverse
                variance of each cutout.
            cutouts_df (pd.dataframe): assumed to contain 'RA' 'DEC'
        """

        # track original list of unique indices
        cutouts_idx_orig = cutouts_df.index.to_numpy()

        # group by healpix coordinate
        cutouts_df = cutouts_df.groupby("healpix")

        # write to the file for the corresponding healpix coordinate
        for group in cutouts_df:

            group_filename = (save_dir+f"healpix={group[0]}/001-of-001.hdf5")
            group_cutouts_df = group[1]

            # only index flux cutouts and ivar cutouts for members of this group
            cutouts_idx_group = group_cutouts_df.index.to_numpy()
            idxs_cutouts = np.asarray(np.where(np.isin(cutouts_idx_orig, cutouts_idx_group))[0])
            group_flux_cutouts = np.asarray(flux_cutouts)[idxs_cutouts]
            group_ivar_cutouts = np.asarray(ivar_cutouts)[idxs_cutouts]

            # Create the output directory if it does not exist
            out_path = os.path.dirname(group_filename)
            if not os.path.exists(out_path):
                print("Creating output directory: ", out_path)
                os.makedirs(out_path, exist_ok=True)

            with FileLock(group_filename + ".lock"):
                if os.path.exists(group_filename):
                    # Load the existing file and concatenate the data with current data
                    with h5py.File(group_filename, 'a') as hdf5_file:

                        # Append image data
                        shape = group_flux_cutouts.shape
                        hdf5_file['image_flux'].resize(hdf5_file['image_flux'].shape[0] + shape[0], axis=0)
                        hdf5_file['image_flux'][-shape[0]:] = group_flux_cutouts

                        # Append ivar data
                        hdf5_file['image_ivar'].resize(hdf5_file['image_ivar'].shape[0] + shape[0], axis=0)
                        hdf5_file['image_ivar'][-shape[0]:] = group_ivar_cutouts

                        # Append unique image ID
                        hdf5_file['object_id'].resize(hdf5_file['object_id'].shape[0] + shape[0], axis=0)
                        hdf5_file['object_id'][-shape[0]:] = group_cutouts_df.index.to_numpy()

                        # Append all info from dataframe (including 'RA','DEC', & 'healpix')
                        for key in group_cutouts_df:
                            # If this key does not already exist, we skip it
                            if key not in hdf5_file:
                                continue
                            shape = group_cutouts_df.loc[:,key].shape
                            hdf5_file[key].resize(hdf5_file[key].shape[0] + shape[0], axis=0)
                            hdf5_file[key][-shape[0]:] = group_cutouts_df.loc[:,key]

                else:           
                    # This is the first time we write the file, so we define the datasets
                    with h5py.File(group_filename, 'w') as h5f:
                        # save the image data.
                        h5f.create_dataset('image_flux', data=group_flux_cutouts)
                        h5f['image_flux'].attrs['description'] = (
                            'Flux values of the cutout images.'
                        )

                        h5f.create_dataset('image_ivar', data=group_ivar_cutouts)
                        h5f['image_ivar'].attrs['description'] = (
                            'Inverse variance maps of the cutout images. '+
                            'Accounts for background noise (sky brightness & read noise)'
                        )

                        # save a unique object_id for each object, tied to their index in
                        # the DataFrame.
                        h5f.create_dataset('object_id', data=group_cutouts_df.index.to_numpy())

                        descriptions={
                            'RA':'Right Ascension of cutout center.',
                            'DEC':'Declination of cutout center.',
                            'healpix':'healpix pixel of cutout.'
                        }

                        # add the remaining data.
                        for key in group_cutouts_df:
                            h5f.create_dataset(
                                    key, data=self._extract_numpy(
                                        group_cutouts_df.loc[:, key]
                                    )
                                )
                            if key in descriptions.keys():
                                h5f[key].attrs['description'] = descriptions[key]
            


    def _download_tile(self, target_name, proposal_id):
        """
        Args:
            target_name (string): ex: 'COSMOS16-10'
            proposal_id (int): proposal id for target in mast query.

        Returns:
            (str): path the file was downloaded to.
        """

        # for each tile, make a folder. In that folder, download the calacs
        # and save cutouts
        target_dir = os.path.join(self.downloads_folder, target_name)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # query MAST using astroquery
        obs_table = Observations.query_criteria(
            proposal_id=proposal_id, target_name=target_name,
            obs_collection='HST', provenance_name='CALACS',
            filters='F814W', dataproduct_type='image'
        )

        data_idx=0
        # if multiple data products found for the same tile,
        if len(obs_table) > 1:
            # use the data product with longer exposure time
            data_idx = np.argmax(obs_table['t_exptime'])
        product_uri = obs_table[data_idx]["dataURL"]

        # download calacs .fits from MAST
        local_path = os.path.join(target_dir, 'calacs.fits')
        _ = Observations.download_file(
            uri=product_uri,
            local_path=local_path
        )

        return local_path

    def process_tiles(self, tile_name_list, proposal_id_list):
        """
        Args:
            tile_name_list ([string]): ex: 'COSMOS16-10'
            proposal_id_list ([int]): proposal id associated to each tile in
                tile_name_list (for COSMOS, either 9822 or 10092)

        Returns:
            - downloads
            saves 'galaxies.h5' and 'foregrounds.h5' to the folder
        """

        # download tiles (if already downloaded, astroquery will skip)
        with ThreadPoolExecutor(max_workers=5) as executor:
            fits_file_list = list(
                executor.map(
                    self._download_tile, tile_name_list, proposal_id_list
                )
            )

        # assign each galaxy to a .fits file (modifies galaxy_df in place)
        fits_col_name = 'fits_file'
        cutout_utils.get_file_for_targets(
            self.cosmos_df, fits_file_list, col_name=fits_col_name
        )

        # Report fraction of galaxies that are assigned a fits file.
        hit_rate = (
            self.cosmos_df['fits_file'].notna().sum() / len(self.cosmos_df)
        )
        print(f'Fraction of galaxies with assigned fits files: {hit_rate:.3f}')

        # generate our random catalog from the boundaries of each of our fits
        # files.
        randoms_df = cutout_utils.get_randoms_from_files(
            self.cosmos_df, fits_file_list, NUMPIX, col_name=fits_col_name
        )

        # add in healpix information
        self.cosmos_df['healpix'] = hp.ang2pix(
                nside=HEALPIX_NSIDE, theta=self.cosmos_df['RA'].to_numpy(), 
                phi=self.cosmos_df['DEC'].to_numpy(),
                lonlat=True, nest=True
            )
        randoms_df['healpix'] = hp.ang2pix(
                nside=HEALPIX_NSIDE, theta=randoms_df['RA'].to_numpy(), 
                phi=randoms_df['DEC'].to_numpy(),
                lonlat=True, nest=True
            )

        # now each galaxy has a .fits file assigned. For each .fits file, make
        # cutouts, and save as an hdf5.
        for fits_file in fits_file_list:

            # load up image, file and wcs
            with fits.open(fits_file) as hdu:
                data_header = hdu[1].header
                flux_tile = hdu[1].data
                weight_tile = hdu[2].data
                wcs = WCS(data_header,hdu)

            # index sources that match this file
            tile_galaxies = self.cosmos_df[
                self.cosmos_df['fits_file']==fits_file
            ]

            # make image and wht cutouts
            flux_cutouts, ivar_cutouts, idxs_cutouts = self.make_cutouts(
                tile_galaxies, flux_tile, weight_tile, wcs
            )
            tile_galaxies = tile_galaxies.loc[idxs_cutouts]

            # save cutouts
            save_dir = self.output_dir+'galaxy_cutouts/'
            self._save_cutouts(
                save_dir, flux_cutouts, ivar_cutouts, tile_galaxies
            )

            tile_randoms = randoms_df[randoms_df['fits_file']==fits_file]

            # make image and wht cutouts
            rand_flux_cutouts, rand_ivar_cutouts, rand_idxs_cutouts = (
                self.make_cutouts(
                    tile_randoms, flux_tile, weight_tile, wcs
                )
            )

            save_dir = self.output_dir+'random_cutouts/'
            self._save_cutouts(
                save_dir, rand_flux_cutouts, rand_ivar_cutouts,
                tile_randoms
            )


def main(args):
    """ Main function for script. """
    # make the cutout class.
    my_cosmos_cutouts = CosmosCutouts(
        metadata_main_path=args.metadata_path,
        morphology_path=args.morphology_path,
        downloads_folder=args.downloads_folder,
        output_dir=args.output_dir,
        nan_tolerance=args.nan_tolerance, 
        zero_tolerance=args.zero_tolerance
    )

    all_targets = list(map(lambda x: (np.load(x)), TARGET_FILES))
    pid_list = [int(x) for x in PID_LIST]

    target_names = np.concatenate(all_targets)
    pids = np.concatenate(list(map(
        lambda targets, pid: np.full(targets.shape, pid), all_targets, pid_list
    )))

    if args.debug:
        print('Debugging with Target: ', target_names[0])
        target_names = [target_names[0]]

    # test with the first tile
    my_cosmos_cutouts.process_tiles(target_names, pids)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Downloads HST COSMOS tiles from MAST"
    )
    parser.add_argument(
        "--nan_tolerance",
        type=float,
        default=1.0,
        help=("Fraction of values that can be nan before cutout is ignored. "+
            "If 1.0, all values can be nans.")
    )
    parser.add_argument(
        "--zero_tolerance",
        type=float,
        default=1.0,
        help=("fraction of values that can be zeros before cutout is ignored. "+
            "If 1.0, all values can be zeros.")
    )
    parser.add_argument(
        "--metadata_path",
        type=str,
        default=None,
        help="metadata path for COSMOS galaxies."   
    )
    parser.add_argument(
        "--morphology_path",
        type=str,
        default=None,
        help="morphology path for COSMOS galaxies."
    )
    parser.add_argument(
        "--downloads_folder",
        type=str,
        default=None,
        help="Where to store COSMOS downloads from MAST."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Where to store cutouts."
    )
    parser.add_argument(
        "--debug",
        type=bool,
        default=False,
        help="If True, only runs on 1st target in list."
    )

    args = parser.parse_args()
    main(args)
