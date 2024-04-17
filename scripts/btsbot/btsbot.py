# Copyright 2020 The HuggingFace Datasets Authors and the current dataset script contributor.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import datasets
from datasets import Features, Value, Array2D, Sequence
from datasets.data_files import DataFilesPatternsDict
import itertools
import h5py
import numpy as np

_CITATION = """\
@misc{rehemtulla2023textttbtsbot,
      title={$\\texttt{BTSbot}$: A Multi-input Convolutional Neural Network to Automate and Expedite Bright Transient Identification for the Zwicky Transient Facility}, 
      author={Nabeel Rehemtulla and Adam A. Miller and Michael W. Coughlin and Theophile Jegou du Laz},
      year={2023},
      eprint={2307.07618},
      archivePrefix={arXiv},
      primaryClass={astro-ph.IM}
}
"""

_DESCRIPTION = """\
This is the production version of the BTSbot training set, limited to public (programid=1) ZTF alerts.
Article: https://arxiv.org/abs/2401.15167
Attribution: Nabeel Rehemtulla, Adam A. Miller, Michael W. Coughlin, Theophile Jegou du Laz -- on behalf of ZTF
"""

_HOMEPAGE = "https://zenodo.org/records/10839691"

_LICENSE = "CC BY 4.0"

_VERSION = "10.0.0"

_FLOAT_FEATURES = [
    'jd',
    'diffmaglim',
    'ra',
    'dec',
    'magpsf',
    'sigmapsf',
    'chipsf',
    'magap',
    'sigmagap',
    'distnr',
    'magnr',
    'chinr',
    'sharpnr',
    'sky',
    'magdiff',
    'fwhm',
    'classtar',
    'mindtoedge',
    'seeratio',
    'magapbig',
    'sigmagapbig',
    'sgmag1',
    'srmag1',
    'simag1',
    'szmag1',
    'sgscore1',
    'distpsnr1',
    'jdstarthist',
    'scorr',
    'sgmag2',
    'srmag2',
    'simag2',
    'szmag2',
    'sgscore2',
    'distpsnr2',
    'sgmag3',
    'srmag3',
    'simag3',
    'szmag3',
    'sgscore3',
    'distpsnr3',
    'jdstartref',
    'dsnrms',
    'ssnrms',
    'magzpsci',
    'magzpsciunc',
    'magzpscirms',
    'clrcoeff',
    'clrcounc',
    'neargaia',
    'neargaiabright',
    'maggaia',
    'maggaiabright',
    'exptime',
    'drb',
    'acai_h',
    'acai_v',
    'acai_o',
    'acai_n',
    'acai_b',
    'new_drb',
    'peakmag',
    'maxmag',
    'peakmag_so_far',
    'maxmag_so_far',
    'age',
    'days_since_peak',
    'days_to_peak',
]

_INT_FEATURES = [
    'label',
    'fid',
    'programid',
    'candid',
    'field',
    'nneg',
    'nbad',
    'ndethist',
    'ncovhist',
    'nmtchps',
    'nnotdet',
    'N',
    'healpix',
]

_BOOL_FEATURES = [
    'isdiffpos',
    'is_SN',
    'near_threshold',
    'is_rise',
]

_STRING_FEATURES = [
    'object_id',
    'source_set',
    'split',
]


class BTSbot(datasets.GeneratorBasedBuilder):
    """BTSbot training set"""

    VERSION = _VERSION
    BUILDER_CONFIGS = [
        datasets.BuilderConfig(name="BTSbot_training_set", 
                               version=VERSION,
                               # TODO: put a proper file path below!
                               #data_files=DataFilesPatternsDict.from_patterns({'train': ['/home/tmh61/rds/hpc-work/datasets/btsbot_processed/healpix=*/*.hdf5']}),
                               data_files=DataFilesPatternsDict.from_patterns({'train': ['/home/tmh61/rds/hpc-work/AstroPile_prototype_BTS/output/healpix=*/*.hdf5']}),
                               description="BTSbot training dataset"),
    ]

    DEFAULT_CONFIG_NAME = "BTSbot_v10"

    _image_size = 63

    _views = ['science', 'reference', 'difference']

    @classmethod
    def _info(self):
        """ Defines the features available in this dataset.
        """
        # Starting with all features common to image datasets
        features = {
            'image': Sequence(feature={
                'view': Value('string'),
                'array': Array2D(shape=(self._image_size, self._image_size), dtype='float32'),
            })
        }
        # Adding all values from the catalog
        for f in _FLOAT_FEATURES:
            features[f] = Value('float32')
        for f in _INT_FEATURES:
            features[f] = Value('int32')
        for f in _BOOL_FEATURES:
            features[f] = Value('bool')
        for f in _STRING_FEATURES:
            # NOTE: includes object_id
            features[f] = Value('string')

        return datasets.DatasetInfo(
            # This is the description that will appear on the datasets page.
            description=_DESCRIPTION,
            # This defines the different columns of the dataset and their types
            features=Features(features),
            # Homepage of the dataset for documentation
            homepage=_HOMEPAGE,
            # License for the dataset if available
            license=_LICENSE,
            # Citation for the dataset
            citation=_CITATION,
        )

    def _split_generators(self, dl_manager):
        """We handle string, list and dicts in datafiles"""
        if not self.config.data_files:
            raise ValueError(f"At least one data file must be specified, but got data_files={self.config.data_files}")
        data_files = dl_manager.download_and_extract(self.config.data_files)
        if isinstance(data_files, (str, list, tuple)):
            files = data_files
            if isinstance(files, str):
                files = [files]
            # Use `dl_manager.iter_files` to skip hidden files in an extracted archive
            files = [dl_manager.iter_files(file) for file in files]
            return [datasets.SplitGenerator(name=datasets.Split.TRAIN, gen_kwargs={"files": files})]
        splits = []
        for split_name, files in data_files.items():
            if isinstance(files, str):
                files = [files]
            # Use `dl_manager.iter_files` to skip hidden files in an extracted archive
            files = [dl_manager.iter_files(file) for file in files]
            splits.append(datasets.SplitGenerator(name=split_name, gen_kwargs={"files": files})) 
        return splits

    def _generate_examples(self, files, object_ids=None):
        """ Yields examples as (key, example) tuples.
        """
        for j, file in enumerate(itertools.chain.from_iterable(files)):
            with h5py.File(file, "r") as file:
                data = file['table']
                if object_ids is not None:
                    keys = object_ids[j]
                else:
                    keys = data["object_id"]
                
                # Preparing an index for fast searching through the catalog
                sort_index = np.argsort(data["object_id"])
                sorted_ids = data["object_id"][:][sort_index]

                for k in keys:
                    # Extract the indices of requested ids in the catalog 
                    i = sort_index[np.searchsorted(sorted_ids, k)]
                    # Parse image data
                    example = {
                        'image': [
                            {
                                'view': view,
                                'array': data['image_triplet'][i, :, :, j],
                            }
                            for j, view in enumerate(self._views)
                        ]
                    }
                    for f in _FLOAT_FEATURES:
                        example[f] = data[f][i].astype('float32')
                    for f in _INT_FEATURES:
                        example[f] = data[f][i].astype('int32')
                    for f in _BOOL_FEATURES:
                        example[f] = data[f][i].astype('bool')
                    for f in _STRING_FEATURES:
                        # NOTE: includes object_id
                        example[f] = data[f][i].astype('str')

                    yield str(data['object_id'][i]), example