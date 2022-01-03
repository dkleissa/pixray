# Originally made by Katherine Crowson (https://github.com/crowsonkb, https://twitter.com/RiversHaveWings)
# The original BigGAN+CLIP method was by https://twitter.com/advadnoun

from DrawingInterface import DrawingInterface

import sys
import subprocess
sys.path.append('v-diffusion-pytorch')
import os.path
import torch
from torch.nn import functional as F
from torchvision.transforms import functional as TF

from omegaconf import OmegaConf
from taming.models import cond_transformer, vqgan

def wget_file(url, out):
    try:
        output = subprocess.check_output(['wget', '-O', out, url])
    except subprocess.CalledProcessError as cpe:
        output = cpe.output
        print("Ignoring non-zero exit: ", output)

from pathlib import Path
MODULE_DIR = Path(__file__).resolve().parent

from diffusion import get_model, get_models, sampling, utils

class ClampWithGrad(torch.autograd.Function):
    @staticmethod
    def forward(ctx, input, min, max):
        ctx.min = min
        ctx.max = max
        ctx.save_for_backward(input)
        return input.clamp(min, max)

    @staticmethod
    def backward(ctx, grad_in):
        input, = ctx.saved_tensors
        return grad_in * (grad_in * (input - input.clamp(ctx.min, ctx.max)) >= 0), None, None

clamp_with_grad = ClampWithGrad.apply

class VdiffDrawer(DrawingInterface):
    @staticmethod
    def add_settings(parser):
        parser.add_argument("--vdiff_model", type=str, help="VDIFF model", default='yfcc_2', dest='vdiff_model')
        # parser.add_argument("--vqgan_config", type=str, help="VQGAN config", default=None, dest='vqgan_config')
        # parser.add_argument("--vqgan_checkpoint", type=str, help="VQGAN checkpoint", default=None, dest='vqgan_checkpoint')
        return parser

    def __init__(self, settings):
        super(DrawingInterface, self).__init__()
        self.vdiff_model = settings.vdiff_model
        self.canvas_width = settings.size[0]
        self.canvas_height = settings.size[1]
        self.iterations = settings.iterations
        self.eta = 1

    def load_model(self, settings, device):
        model = get_model(self.vdiff_model)()
        checkpoint = MODULE_DIR / f'checkpoints/{self.vdiff_model}.pth'
        model.load_state_dict(torch.load(checkpoint, map_location='cpu'))
        if device.type == 'cuda':
            model = model.half()
        model = model.to(device).eval().requires_grad_(False)

        self.model = model
        self.device = device
        self.pred = None
        self.v = None
        self.x = torch.randn([1, 3, self.canvas_height, self.canvas_width], device=self.device)
        self.x.requires_grad_(True)
        self.t = torch.linspace(1, 0, self.iterations+2, device=self.device)[:-1]
        self.steps = utils.get_spliced_ddpm_cosine_schedule(self.t)

        self.sample_state = sampling.sample_setup(self.model, self.x, self.steps, self.eta, {})


    def get_opts(self, decay_divisor):
        return None

    def rand_init(self, toksX, toksY):
        # legacy init
        return None

    def init_from_tensor(self, init_tensor):
        # self.z, *_ = self.model.encode(init_tensor)        
        # self.z.requires_grad_(True)
        next_x = torch.randn([1, 3, self.canvas_height, self.canvas_width], device=self.device)
        self.x.requires_grad_(True)
        self.pred = None 
        self.v = None 

    def reapply_from_tensor(self, new_tensor):
        return None

    def get_z_from_tensor(self, ref_tensor):
        return None

    def get_num_resolutions(self):
        return None

    def makenoise(self, cur_it):
        return sampling.noise(self.sample_state, self.x, cur_it, self.pred, self.v).detach()

    def synth(self, cur_iteration):
        pred, v, next_x = sampling.sample_step(self.sample_state, self.x, cur_iteration, self.pred, self.v)
        pixels = clamp_with_grad(pred.add(1).div(2), 0, 1)
        # save a copy for the next iteration
        self.pred = pred.detach()
        self.v = v.detach()
        return pixels

    @torch.no_grad()
    def to_image(self):
        out = self.synth(None)
        return TF.to_pil_image(out[0].cpu())

    def clip_z(self):
        return None

    def get_z(self):
        return self.x

    def set_z(self, new_z):
        with torch.no_grad():
            return self.x.copy_(new_z)

    def get_z_copy(self):
        return self.x.clone()
        # return model, gumbel
