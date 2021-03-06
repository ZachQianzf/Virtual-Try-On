# coding=utf-8
import torch
import torch.utils.data as data
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, Dataset
from PIL import Image
from PIL import ImageDraw
from addict import Dict
import os.path as osp
import numpy as np
import argparse
import matplotlib.pyplot as plt
import sys
import cv2
import json

class CPDataset(data.Dataset):
    def __init__(self, opt):
        super(CPDataset, self).__init__()
        # base setting
        self.opt = opt

        self.dataroot = opt.data.files.base

        if opt.model.is_train:
            self.datamode = "train"
            self.data_list = opt.data.files.train
        else:
            self.datamode = "test"
            self.data_list = opt.data.files.test


        print(self.data_list)
        self.fine_height = opt.data.transforms.height
        self.fine_width = opt.data.transforms.width
        self.radius = opt.data.transforms.radius

        self.data_path = osp.join(self.dataroot, self.datamode)

        self.transform = transforms.Compose(
            [transforms.ToTensor(), transforms.Normalize((0.5,), (0.5,))]
        )

        # load data list
        im_names = []
        c_names = []

        with open(osp.join(self.dataroot, self.data_list), "r") as f:
            print(f)
            for line in f.readlines():
                im_name, c_name = line.strip().split()
                im_names.append(im_name)
                c_names.append(c_name)

        self.im_names = im_names
        self.c_names = c_names

    def name(self):
        return "CPDataset"

    def __getitem__(self, index):
        c_name = self.c_names[index]
        im_name = self.im_names[index]

        # cloth image & cloth mask
        c = Image.open(osp.join(self.data_path, "cloth", c_name))
        #c.show()
        cm = Image.open(osp.join(self.data_path, "cloth-mask", c_name))

        c = self.transform(c)  # [-1,1]
        cm_array = np.array(cm)
        cm_array = (cm_array >= 128).astype(np.float32)
        cm = torch.from_numpy(cm_array)  # [0,1]
        cm.unsqueeze_(0)

        # person image
        im = Image.open(osp.join(self.data_path, "image", im_name))
        im = self.transform(im)  # [-1,1]

        # load parsing image
        parse_name = im_name.replace(".jpg", ".png")
        im_parse = Image.open(osp.join(self.data_path, "image-parse", parse_name))
        parse_array = np.array(im_parse)

        # -------Find segmentation class labels manually
        #Image1 = Image.open(osp.join(self.data_path, 'image-parse', parse_name))
        Image2 = Image.open(osp.join(self.data_path, "image", im_name))

        #plt.imshow(Image1)
        #plt.imshow(parse_array, alpha=0.5)
        #plt.imshow(Image2)

        #plt.colorbar()
        #plt.show()
        # shirt = 126, pants = 59
        # hair = 76, face = 29
        # ------End

        parse_shape = (parse_array > 0).astype(np.float32)

        parse_cloth = (parse_array == 126).astype(np.float32)

        # get cropped top img
        source = Image.open(osp.join(self.data_path, "image", im_name))
        mask = Image.fromarray(np.uint8(255 * parse_cloth)).convert("L")
        blankImg = Image.new("RGB", (self.fine_height, self.fine_width), (255, 255, 255))

        imgCropped = Image.composite(source, blankImg, mask)
        #imgCropped.show()
        #mask.show()
        imgCropped = self.transform(imgCropped)  # [-1,1]

        # shape downsample
        parse_shape = Image.fromarray((parse_shape * 255).astype(np.uint8))
        parse_shape = parse_shape.resize(
            (self.fine_width // 16, self.fine_height // 16), Image.BILINEAR
        )
        parse_shape = parse_shape.resize((self.fine_width, self.fine_height), Image.BILINEAR)
        shape = self.transform(parse_shape)  # [-1,1]
        pcm = torch.from_numpy(parse_cloth)  # [0,1]
        #plt.imshow(pcm)
        #plt.show()

        # clean up
        im_c = im * pcm + (1 - pcm)  # [-1,1], fill 1 for other parts

        pcm = pcm.unsqueeze_(0) 

        #-----pose
        pose_name = im_name.replace('.jpg', '_keypoints.json')
        with open(osp.join(self.data_path, 'pose', pose_name), 'r') as f:
            pose_label = json.load(f)
            pose_data = pose_label['people'][0]['pose_keypoints']
            pose_data = np.array(pose_data)
            pose_data = pose_data.reshape((-1,3))

        point_num = pose_data.shape[0]
        pose_map = torch.zeros(point_num, self.fine_height, self.fine_width)
        r = self.radius
        im_pose = Image.new('L', (self.fine_width, self.fine_height))
        pose_draw = ImageDraw.Draw(im_pose)
        for i in range(point_num):
            one_map = Image.new('L', (self.fine_width, self.fine_height))
            draw = ImageDraw.Draw(one_map)
            pointx = pose_data[i,0]
            pointy = pose_data[i,1]
            if pointx > 1 and pointy > 1:
                draw.ellipse((pointx-r, pointy-r, pointx+r, pointy+r), 'white', 'white')
                pose_draw.ellipse((pointx-r, pointy-r, pointx+r, pointy+r), 'white', 'white')
            #plt.imshow(one_map, cmap='jet', alpha=.9)
            #plt.show()
            one_map = self.transform(one_map) #[-1,1]
            pose_map[i] = one_map[0]

        #plt.imshow(im_pose, cmap='jet', alpha=0.5)
        #plt.show()

        #for i in range(18):
        #    show_ = np.squeeze(pose_map[i])
        #    plt.imshow(Image2)
        #    plt.imshow(show_, cmap="jet", alpha=.5)
        #    plt.show()

        #just for visualization
        im_pose = self.transform(im_pose)


        result = {
            "c_name": c_name,  # for visualization
            "im_name": im_name,  # for visualization or ground truth
            "pose_image": im_pose, #visualize pose, can overlay with image for better visualization
            "pose": pose_map, #for input
            "cloth": c,  # for input
            "cloth_mask": cm,  # for input
            "image": imgCropped,  # for visualization
            "parse_cloth": pcm,  # was im_c  # for ground truth
            "shape": shape,  # for visualization
        }

        return Dict(result)

    def __len__(self):
        return len(self.im_names)


class CPDataLoader(object):
    def __init__(self, opt, dataset):
        super(CPDataLoader, self).__init__()

        if opt.data.loaders.shuffle:
            train_sampler = torch.utils.data.sampler.RandomSampler(dataset)
        else:
            train_sampler = None

        self.data_loader = torch.utils.data.DataLoader(
            dataset,
            batch_size=opt.data.loaders.batch_size,
            shuffle=(train_sampler is None),
            num_workers=opt.data.loaders.num_workers,
            pin_memory=True,
            sampler=train_sampler,
        )
        self.dataset = dataset
        self.data_iter = self.data_loader.__iter__()

    def next_batch(self):
        try:
            batch = self.data_iter.__next__()
        except StopIteration:
            self.data_iter = self.data_loader.__iter__()
            batch = self.data_iter.__next__()

        return batch


def get_loader(opts):
    return DataLoader(
        CPDataset(opts),
        batch_size=opts.data.loaders.get("batch_size", 4),
        shuffle=True,
        num_workers=opts.data.loaders.get("num_workers", 8),
    )
