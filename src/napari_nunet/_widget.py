from magicgui import magicgui
from magicgui.tqdm import tqdm
import torch
import napari
from napari.types import ImageData
from napari.layers import Image
import numpy as np
from napari.qt.threading import thread_worker
import time
from pathlib import Path
from typing import Optional
import os

from nunet.config import SelfConfig
from nunet.utils import load_model, numpy2torch, torch2numpy, load_weights, make_sw_list, find_sw_cfg, load_all_models
from .img_utils import img_reshape_axes, detect_axes, img_postprocess_reshape, check_input_axes
from nunet.transformer_net import TransformerNet

# Resources
cfg_file = Path(
    "C:/Users/hp/Desktop/PRe/nunet/config/self_ultimate_vgg19_lr1e-4_e20_sw100.yml")
cfg_folder = Path("C:/Users/hp/Desktop/PRe/nunet/configs_filter_slider/")
models_folder = Path("C:/Users/hp/Desktop/PRe/nunet/models_filter_slider")
lob_logo_path = "C:/Users/hp/Desktop/PRe/napari-nunet/src/resources/Logo_LOB.png"


def grayscale_nunet(img: ImageData, model: TransformerNet, with_cuda: bool):
    """Applies a nunet trained model to a grayscale Image

    Parameters
    ----------
    img : ImageData
        Layer data to apply the model to
    model : TransformerNet
        Trained nunet model
    with_cuda : bool
        If True, input tensor will be loaded on GPU

    Returns
    -------
    out_np_clipped : NDArray[float]
        The output numpy array
    """
    tensor = numpy2torch(img, cuda=with_cuda)
    out_tensor = model(tensor)
    out_tensor_clipped = torch.clip(out_tensor, 0, 255)
    out_np_clipped = torch2numpy(out_tensor_clipped)/255.0
    return out_np_clipped


def run_nunet(img: ImageData, axes: str, with_cuda: bool,  cfg: Optional[Path] = None, model: Optional[TransformerNet] = None):
    """Parses the input image and applies nunet on every grayscale subimage.

    Parameters
    ----------
    img : ImageData
        Layer data to apply the model to
    axes : str
        Axes of the image in format TCZYX
    with_cuda : bool
        If True, the model will be loaded on GPU
    cfg: Optional[Path]
        Path to the config file if model is not preloaded
    model: Optional[TransformerNet]
        Preloaded model

    Returns
    -------
    output_image : ndarray
        The output numpy array
    """
    if cfg is not None:
        cfg = SelfConfig(cfg)
        nu_net = load_model(cfg, with_cuda=with_cuda)[2]
    elif model is not None:
        nu_net = model
    else:
        raise ValueError(
            'No config file path nor model file specified, please specifiy either one or the other')

    img = img_reshape_axes(img, axes)  # output in TCZYX format

    shape = img.shape
    nb_images = shape[0]*shape[1]*shape[2]
    progress_step = 100/nb_images
    progress = 0

    img_output = np.empty_like(img, dtype=np.float32)

    with torch.no_grad():
        for i in range(shape[0]):
            for j in range(shape[1]):
                for k in range(shape[2]):
                    img_output[i, j, k, :, :] = grayscale_nunet(
                        img[i, j, k, :, :], nu_net, with_cuda)
                    progress += progress_step
                    if progress > int(progress):
                        nunet_plugin.progressbar.value = int(progress)

    img_output = img_postprocess_reshape(img_output, axes)

    return img_output


def weighted_sum(img: ImageData, axes: str, slider_value: float, sw_list: list):
    """Computes the weighted sum between two models when needed, in order to have 
    various filtering intensities.

    Parameters
    ----------
    img : ImageData
        Layer data to apply the model to
    axes : str
        Axes of the image in format TCZYX
    slider_value : float
        Value of the slider widget
    sw_list : list
        List of all the sw values in trained models folder

    Returns
    -------
    img_output : ndarray
        The output numpy array
    """
    all_loaded = nunet_plugin_wrapper.load_on_launch
    with_cuda = nunet_plugin_wrapper.with_cuda
    weighted, sw1, sw2, weight1, weight2 = load_weights(slider_value, sw_list)

    if slider_value == 0.0:
        return img

    if not weighted or sw1 == None or sw2 == None:
        sw = sw1 if sw1 is not None else sw2
        if all_loaded:
            all_models = nunet_plugin_wrapper.all_models
            img_output = run_nunet(img, axes, with_cuda, model=all_models[sw])
        else:
            cfg_file = Path(os.path.join(
                cfg_folder, find_sw_cfg(sw, cfg_folder)))
            img_output = run_nunet(img, axes, with_cuda, cfg=cfg_file)
    else:
        if all_loaded:
            all_models = nunet_plugin_wrapper.all_models
            img_out1 = run_nunet(img, axes, with_cuda, model=all_models[sw1])
            img_out2 = run_nunet(img, axes, with_cuda, model=all_models[sw2])
        else:
            cfg_file1 = cfg_file = Path(os.path.join(
                cfg_folder, find_sw_cfg(sw1, cfg_folder)))
            cfg_file2 = cfg_file = Path(os.path.join(
                cfg_folder, find_sw_cfg(sw2, cfg_folder)))
            img_out1 = run_nunet(img, axes, with_cuda, cfg=cfg_file1)
            img_out2 = run_nunet(img, axes, with_cuda, cfg=cfg_file2)

        img_output = weight1*img_out1 + weight2*img_out2

    return(img_output)


def nunet_plugin_wrapper():
    """Plugin wrapper, returns the plugin in order to retrieve its output value.
    """
    return nunet_plugin


# Set new attributes to the wrapper, these will be used as global variables

# Checks if cuda is available on the machine
setattr(nunet_plugin_wrapper, 'with_cuda', torch.cuda.is_available())

# Sets whether the models should be laoded on plugin launch or when called
setattr(nunet_plugin_wrapper, 'load_on_launch', True)

# Loads the models regarding if required
if nunet_plugin_wrapper.load_on_launch:
    setattr(nunet_plugin_wrapper, 'all_models', load_all_models(
        models_folder, with_cuda=nunet_plugin_wrapper.with_cuda))
    print("All models have been loaded successfully.")
else:
    print("Required models will be loaded on call.")

# Checks if the layer list is empty
setattr(nunet_plugin_wrapper, 'empty_layer_list', True)


@ magicgui(axes=dict(widget_type="LineEdit", label="Axes",
                     tooltip="T: time\nC: channels\nZ: depth\nY: width\nX: height"),
           call_button="Run NU-Net", image=dict(label="Image"),
           label_head=dict(widget_type="Label",
                           label=f'<img src="{lob_logo_path}">'),
           slider=dict(widget_type="FloatSlider", label="Intensity",
                       value=5.0, min=0.0, max=10.0, step=0.5),
           run_device=dict(widget_type="RadioButtons", label="Device", choices=[
                           "CPU", "GPU (recommended)"], orientation="horizontal", value="GPU (recommended)"),
           progressbar=dict(widget_type="ProgressBar",
                            label="Processing", min=0, max=100, visible=False),
           info_label=dict(widget_type="Label", visible=False))
def nunet_plugin(label_head, image: Image, axes, slider, run_device, progressbar, info_label) -> ImageData:
    """Widget that applies NU-Net to an image

    Parameters
    ----------
    img : Image
        Layer data to apply the model to

    Returns
    -------
    output : ImageData
        The transformed image layer
    """
    nunet_plugin.progressbar.visible = True
    nunet_plugin.progressbar.value = 0
    nunet_plugin.info_label.visible = False

    if nunet_plugin_wrapper.load_on_launch:
        sw_list = list(nunet_plugin_wrapper.all_models.keys())
        sw_list.sort()
    else:
        sw_list = make_sw_list(cfg_folder)

    if image is not None:
        t0 = time.time()
        try:
            image_output = weighted_sum(image.data, axes, slider, sw_list)
        except:
            print("Wrong Axis Specification : please fix them and retry")
            nunet_plugin.info_label.label = "Error"
            nunet_plugin.progressbar.visible = False
            nunet_plugin.info_label.visible = True
            nunet_plugin.info_label.native.setStyleSheet(
                "font : bold 14px; height : 32px; color : lightcoral")
            nunet_plugin.info_label.value = "Wrong Axis Specification : please fix them and retry"
            print(nunet_plugin.info_label.height)
        else:
            nunet_plugin.progressbar.value = 100
            t1 = time.time()
            print(f'Executed in {(t1 - t0) / 60:.2f} minutes')
            nunet_plugin.info_label.visible = True
            nunet_plugin.info_label.label = "Success"
            nunet_plugin.info_label.native.setStyleSheet(
                "font : bold 14px; height : 32px; color : lightgreen")
            nunet_plugin.info_label.value = f'Executed in {(t1 - t0):.2f} seconds'
        return image_output


# Customization with Qt
nunet_plugin.label_head.value = '<p style="text-align: center; line-height: 0.8;"><h1><span style="font-family: Trebuchet MS, Helvetica, sans-serif;">NU-Net</span></h1></p><p style="text-align: center; line-height: 0.5;"><span style="font-family: "Trebuchet MS", Helvetica, sans-serif font-size: 10px"><em>Generic segmentation for bioimages</em></span></p><p style="text-align: center; line-height: 0.5;"><span style="font-family: "Trebuchet MS", Helvetica, sans-seriffont-size: 6px"><em><a href="https://github.com/tangnrolle/napari_nunet_dev">Github Repository</a></em></span></p><p style="text-align: center; line-height: 1.00;"><span style="font-family: "Trebuchet MS", Helvetica, sans-serif font-size: 8px"><em>V.0.0.1</em></span></p>'
if nunet_plugin.image.value is not None:
    nunet_plugin.axes.native.setMaxLength(nunet_plugin.image.value.data.ndim)
else:
    nunet_plugin.axes.native.setMaxLength(5)
nunet_plugin.info_label.visible = False
nunet_plugin.info_label.native.setStyleSheet("font : bold 14px; height : 32px")

# Change handlers

# Reinitialize some widget values when layer list is emptied


@nunet_plugin.image.native.currentIndexChanged.connect
def img_layer_currIndexChanged(val):
    if val == -1:
        nunet_plugin_wrapper.empty_layer_list = True
        nunet_plugin.axes.value = ''
        nunet_plugin.axes.label = "Axes"
        nunet_plugin.progressbar.visible = False

# Change some widget values whenever the selected image changes


@ nunet_plugin.image.changed.connect
def change_image(new_img: Image):
    nunet_plugin.info_label.visible = False
    nunet_plugin.progressbar.visible = False
    if new_img is not None:
        nunet_plugin_wrapper.empty_layer_list = False
        nunet_plugin.axes.native.setMaxLength(
            nunet_plugin.image.value.data.ndim)
        nunet_plugin.axes.native.setText(
            detect_axes(new_img.data))
        nunet_plugin.axes.tooltip = "axes"  # TODO
        nunet_plugin.axes.label = "Axes (guessed)"
    else:
        nunet_plugin.axes.value = ''

# Compute some tests whenever the user tries to change the axes value


@ nunet_plugin.axes.changed.connect
def change_axes(new_axes: str):
    nunet_plugin.info_label.visible = False
    if not nunet_plugin_wrapper.empty_layer_list:
        new_axes, check = check_input_axes(
            new_axes, nunet_plugin.image.value.data)
        nunet_plugin.axes.value = new_axes
        nunet_plugin.axes.label = "Axes"
        if check:
            nunet_plugin.call_button.enabled = True
            nunet_plugin.call_button.text = "Run NU-Net"
            nunet_plugin.call_button.native.setStyleSheet("")
            nunet_plugin.axes.native.setStyleSheet("")
            print("Axes of the current layer image have been set to", new_axes)
        else:
            nunet_plugin.call_button.enabled = False
            nunet_plugin.axes.native.setStyleSheet(
                "background-color: lightcoral")
            nunet_plugin.call_button.native.setStyleSheet(
                "background-color: lightcoral")
            nunet_plugin.call_button.text = "Incorrect Axes"
    else:
        nunet_plugin.call_button.native.setStyleSheet(
            "background-color: lightcoral")
        nunet_plugin.call_button.text = "No Image Selected"

# Reload all models on new device when users selects a new one


@nunet_plugin.run_device.changed.connect
def change_device(new_device: str):
    if new_device == "CPU":
        setattr(nunet_plugin_wrapper, 'with_cuda', False)
    elif new_device == "GPU (recommended)":
        setattr(nunet_plugin_wrapper, 'with_cuda', True)

    setattr(nunet_plugin_wrapper, 'all_models', load_all_models(
        models_folder, with_cuda=nunet_plugin_wrapper.with_cuda))


# Since the step parameter does not work in the current magicgui version, this is a fix


@ nunet_plugin.slider.changed.connect
def fixed_slider(new_value: float):
    if new_value % 1 >= nunet_plugin.slider.step/2:
        nunet_plugin.slider.value = int(new_value) + nunet_plugin.slider.step
    else:
        nunet_plugin.slider.value = int(new_value)
