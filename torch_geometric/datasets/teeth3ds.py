import json
import os
import os.path as osp
from glob import glob
from typing import Callable, Dict, List, Optional

import numpy as np
import torch
import trimesh
from fpsample import bucket_fps_kdline_sampling
from tqdm import tqdm

from torch_geometric.data import (
    Data,
    InMemoryDataset,
    download_url,
    extract_zip,
)


class Teeth3DS(InMemoryDataset):
    r"""Teeth3DS+, An Extended Benchmark for Intra-oral 3D Scans Analysis."""
    """
    is the first comprehensive public benchmark designed to advance the
    field of intra-oral 3D scan analysis.
    Developed as part of the 3DTeethSeg 2022 and 3DTeethLand 2024 MICCAI
    challenges, Teeth3DS+ aims to drive research in teeth identification,
    segmentation, labeling, 3D modeling, and dental landmark identification.
    The dataset includes at least 1,800 intra-oral scans
    (containing 23,999 annotated teeth) collected from 900 patients,
    covering both upper and lower jaws separately.
    <https://crns-smartvision.github.io/teeth3ds/>

    Args:
        root (str): Root directory where the dataset is stored
                    or will be downloaded.
        split (str): Dataset split name, e.g., "Teeth3DS".
                     or ["3DTeethSeg22_challenge", "3DTeethLand_challenge"].
        is_train (bool, optional): If True, use the training set;
                                   otherwise, use the test set.
        n_sample (int, optional): Number of points to sample from each mesh.
                                  Default is 30000.
        transform (callable, optional): A function/transform that takes in an
            :obj:`torch_geometric.data.Data` object and returns a transformed
            version. The data object will be transformed before every access.
            (default: :obj:`None`)
        pre_transform (callable, optional): A function/transform that takes in
            an :obj:`torch_geometric.data.Data` object and returns a
            transformed version. The data object will be transformed before
            being saved to disk. (default: :obj:`None`)
        pre_filter (callable, optional): A function that takes in an
            :obj:`torch_geometric.data.Data` object and returns a boolean
            value, indicating whether the data object should be included in the
            final dataset. (default: :obj:`None`)
        force_reload (bool, optional): Whether to re-process the dataset.
            (default: :obj:`False`)
    """

    urls = {
        "data_part_1.zip":
        'https://osf.io/download/qhprs/',
        "data_part_2.zip":
        'https://osf.io/download/4pwnr/',
        "data_part_3.zip":
        'https://osf.io/download/frwdp/',
        "data_part_4.zip":
        'https://osf.io/download/2arn4/',
        "data_part_5.zip":
        'https://osf.io/download/xrz5f/',
        "data_part_6.zip":
        'https://osf.io/download/23hgq/',
        "data_part_7.zip":
        'https://osf.io/download/u83ad/',
        "train_test_split":
        "https://files.de-1.osf.io/v1/"
        "resources/xctdy/providers/osfstorage/?zip="
    }

    landmarks_urls = {
        "3DTeethLand_landmarks_train.zip": 'https://osf.io/download/k5hbj/',
        "3DTeethLand_landmarks_test.zip": 'https://osf.io/download/sqw5e/',
    }

    def __init__(
        self,
        root: str,
        split: str = "Teeth3DS",
        # [3DTeethSeg22_challenge, 3DTeethLand_challenge]
        is_train: bool = True,
        n_sample: int = 30000,
        transform: Optional[Callable] = None,
        pre_transform: Optional[Callable] = None,
        pre_filter: Optional[Callable] = None,
        force_reload: bool = False,
    ) -> None:
        self.mode = "training" if is_train else "testing"
        self.split = split
        self.n_sample = n_sample
        super().__init__(root, transform, pre_transform, pre_filter,
                         force_reload=force_reload)

    @property
    def processed_dir(self) -> str:
        return os.path.join(self.root, f"processed_{self.split}_{self.mode}")

    @property
    def raw_file_names(self) -> List[str]:
        return ['license.txt']

    @property
    def processed_file_names(self) -> List[str]:
        # Directory containing train/test split files
        split_dir = osp.join(self.raw_dir, f'{self.split}_train_test_split')
        split_files = glob(osp.join(split_dir, f'{self.mode}*.txt'))

        # Collect all file names from the split files
        combined_list = []
        for file_path in split_files:
            with open(file_path) as file:
                combined_list.extend(file.read().splitlines())

        # Generate the list of processed file paths
        return [f"{file_name}.pt" for file_name in combined_list]

    def download(self) -> None:
        for key, url in self.urls.items():
            path = download_url(url, self.root, filename=key)
            extract_zip(path, self.raw_dir)
            os.unlink(path)
        # download landmarks
        for key, url in self.landmarks_urls.items():
            path = download_url(url, self.root, filename=key)
            extract_zip(path, self.raw_dir)  # Extract each downloaded part
            os.unlink(path)

    def process_file(self, file_path: str) -> Optional[Data]:
        """Processes the input file path to load mesh data, annotations,
        and prepare the input features for a graph-based deep learning model.

        Args:
            file_path (str): Path to the `.obj` file representing the mesh.

        Returns:
            Data: A PyTorch Geometric Data object containing processed data.
        """
        # Load mesh
        mesh = trimesh.load_mesh(file_path)
        if isinstance(mesh, list):
            # Handle the case where a list of Geometry objects is returned
            mesh = mesh[0]  # Choose the first mesh
        # Perform sampling on mesh vertices
        if len(mesh.vertices) < self.n_sample:
            sampled_indices = np.random.choice(len(mesh.vertices),
                                               self.n_sample, replace=True)
        else:
            sampled_indices = bucket_fps_kdline_sampling(
                mesh.vertices, self.n_sample, h=5, start_idx=0)
        assert len(sampled_indices) == self.n_sample, (
            f"Sampled points mismatch: Expected {self.n_sample},"
            f" but got {len(sampled_indices)} for {file_path}")
        # Extract features and annotations for the sampled points
        pos = torch.tensor(mesh.vertices[sampled_indices], dtype=torch.float)
        x = torch.tensor(mesh.vertex_normals[sampled_indices],
                         dtype=torch.float)

        # Load segmentation annotations
        seg_annotation_path = file_path.replace('.obj', '.json')
        if osp.exists(seg_annotation_path):
            with open(seg_annotation_path) as f:
                seg_annotations = json.load(f)
            y = torch.tensor(
                np.asarray(seg_annotations['labels'])[sampled_indices],
                dtype=torch.float)
            instances = torch.tensor(
                np.asarray(seg_annotations['instances'])[sampled_indices],
                dtype=torch.float)
        else:
            y = torch.empty(0, 3)
            instances = torch.empty(0, 3)
        # Load landmarks annotations
        landmarks_annotation_path = file_path.replace('.obj', '__kpt.json')
        # Parse keypoint annotations into structured tensors
        keypoints_dict: Dict[str, List] = {
            key: []
            for key in [
                'Mesial', 'Distal', 'Cusp', 'InnerPoint', 'OuterPoint',
                'FacialPoint'
            ]
        }
        keypoint_tensors: Dict[str, torch.Tensor] = {
            key: torch.empty(0, 3)
            for key in [
                'Mesial', 'Distal', 'Cusp', 'InnerPoint', 'OuterPoint',
                'FacialPoint'
            ]
        }
        if osp.exists(landmarks_annotation_path):
            with open(landmarks_annotation_path) as f:
                landmarks_annotations = json.load(f)

            for keypoint in landmarks_annotations['objects']:
                keypoints_dict[keypoint["class"]].extend(keypoint["coord"])

            keypoint_tensors = {
                k: torch.tensor(np.asarray(v),
                                dtype=torch.float).reshape(-1, 3)
                for k, v in keypoints_dict.items()
            }
        # Create the PyTorch Geometric Data object
        data = Data(pos=pos, x=x, y=y, instances=instances,
                    jaw=file_path.split('.obj')[0].split('_')[1],
                    mesial=keypoint_tensors['Mesial'],
                    distal=keypoint_tensors['Distal'],
                    cusp=keypoint_tensors['Cusp'],
                    inner_point=keypoint_tensors['InnerPoint'],
                    outer_point=keypoint_tensors['OuterPoint'],
                    facial_point=keypoint_tensors['FacialPoint'])

        # Apply optional pre-filter and pre-transform if specified
        if self.pre_filter is not None and not self.pre_filter(data):
            return None
        if self.pre_transform is not None:
            data = self.pre_transform(data)

        return data

    def process(self) -> None:
        for file in tqdm(self.processed_file_names):
            file_name = file.split('.')[0]
            file_path = glob(self.raw_dir + '/**/*/*' + file_name + '.obj')
            if len(file_path) == 1:
                data = self.process_file(file_path[0])
                torch.save(data, osp.join(self.processed_dir, file))

    def len(self) -> int:
        return len(self.processed_file_names)

    def get(self, idx: int) -> Data:
        file = self.processed_file_names[idx]
        data = torch.load(osp.join(self.processed_dir, file))
        return data

    def __repr__(self) -> str:
        return (f'{self.__class__.__name__}({len(self)}, '
                f'mode={self.mode}, split={self.split})')


if __name__ == '__main__':
    dataset_train = Teeth3DS(root="./Teeth3DS", split="Teeth3DS")
    print(dataset_train)
    dataset_test = Teeth3DS(root="./Teeth3DS", split="Teeth3DS",
                            is_train=False)
    print(dataset_test)
