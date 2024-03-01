# -*- mode: python -*-
# =============================================================================
# @@-COPYRIGHT-START-@@
#
# Copyright (c) 2023 of Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
#
# @@-COPYRIGHT-END-@@
# =============================================================================
from flask import Blueprint
from flask import request, jsonify, make_response, send_file, render_template
from PIL import Image
from empatches import EMPatches
import io, os
import cv2
import numpy as np
import zmq

from datetime import datetime
import time

import globalvar
# from utils import pyinstaller_absolute_path

time_taken_model = ""
upscaled_img_dims = ""

superRes_bp = Blueprint("SuperRes",__name__)

runtime_name_decoder={'DSP':b"DSP",'GPU':b"GPU", 'CPU':b"CPU"}
# dlc_name_decoder={'ESRGAN':'quant_ESRGAN_128_512_8350_214.dlc', 'SRGAN':'quant_SRGAN_128_512_8350_214.dlc', 'SESR':'quant_SESR_128_512_8350_214.dlc','QuickSR_large':'quant_quickSRnet_large_128_512_8350_214.dlc','QuickSR_medium':'quant_quickSRnet_medium_128_512_8350_214.dlc','QuickSR_small':'quant_quickSRnet_small_128_512_8350_214.dlc','XLSR':'quant_XLSR_128_512_8350_214.dlc'}
dlc_name_decoder={'ESRGAN':'quant_ESRGAN_128_4_8350.dlc', 'SRGAN':'quant_SRGAN_128_512_8350.dlc', 'SESR':'quant_SESR_128_512_8350.dlc','QuickSR_large':'quant_quickSRnet_large_128_512_8350.dlc','QuickSR_medium':'quant_quickSRnet_medium_128_512_8350.dlc','QuickSR_small':'quant_quickSRnet_small_128_512_8350.dlc','XLSR':'quant_XLSR_128_512_8350.dlc'}

@superRes_bp.route('/sr_checkdlc', methods=['POST'])
def checkdlc():
    print("checkdlc: ")
    from flask import jsonify
    import os
    model_name = request.form.get('model_name')
    
    print("MODEL NAME IN CHECKDLC: ", model_name)
    dlc_path = os.path.join("C:\Qualcomm\AIStack\AI_Solutions\DLC","superresolution", dlc_name_decoder.get(model_name))
    if(os.path.isfile(dlc_path)):
        print("found")
        output_new = {
                "dlc_available": "yes",
                "dlc_path" : dlc_path
            }
    else:
        print("not found")
        output_new = {
                "dlc_available": "no",
                "dlc_path" : dlc_path
            }
    return jsonify(output_new), 200
def buildnetwork(socket, model_name, run_time):

    print("BUILDING NETWORK")
    first_str = b"networkbuild"
    

    dlc_path = bytes(os.path.join("C:\Qualcomm\AIStack\AI_Solutions\DLC","superresolution", dlc_name_decoder.get(model_name)),'utf-8')
    
    socket.send_multipart([first_str,dlc_path, runtime_name_decoder.get(run_time)])   

    print("Messages sent for building network, waiting for reply")
    message_build = socket.recv()
    print(message_build)

def upscale_patch(socket, patch, model_name, run_time, scaling_factor=4 ):
    
    try:
        print("MODEL::::::::::::::::::::::")
        runtime_name_decoder={'DSP':"--use_dsp",'GPU':"--use_gpu", 'CPU':""}
        # dlc_name_decoder={'ESRGAN':'quant_ESRGAN_128_4_8350.dlc', 'SRGAN':'quant_SRGAN_128_512_8350.dlc', 'SESR':'quant_SESR_128_512_8350.dlc','QuickSR_large':'quant_quickSRnet_large_128_512_8350.dlc','QuickSR_medium':'quant_quickSRnet_medium_128_512_8350.dlc','QuickSR_small':'quant_quickSRnet_small_128_512_8350.dlc','XLSR':'quant_XLSR_128_512_8350.dlc'}
        # dlc_path = os.path.join("sr_dlc", dlc_name_decoder.get(model_name))
        
        ## PREPROC ##
        start = time.time()
        if model_name=='ESRGAN':
            # do nothing #
            print("no preproc needed---Only resize")
        
        else:
            patch = patch/255
        end = time.time()
        print("preprocess Time: ", end-start)
        
        img = np.array(patch)
        img = img.astype(np.float32)
        img = img.tobytes()

        socket.send_multipart([b"infer",img])

        print("Messages Image sent, waiting for reply")
        message_img_out = socket.recv()

        prediction = np.frombuffer(message_img_out, dtype=np.float32)
        #print("Message received from server :: Shape: ", prediction.shape," data: ", prediction)

        print("inf_result.shape:: ",prediction.shape)
        print("First Value of vector in python: ",prediction[0])
        print("Last 5 Value of vector in python: ",prediction[prediction.shape[0]-5:])
        
        socket.send(b"get_infer_time")
        message_infer_time = socket.recv()
        print("message_infer_time", message_infer_time.decode('UTF-8'))
        elapsed_time = 0.0
        elapsed_time = float(message_infer_time.decode('UTF-8'))/1000

        start = time.time()
        prediction = prediction.reshape(512,512,3)
            
        ## POSTPROC ##
        if model_name=='ESRGAN':
            # do nothing #
            print("no postproc needed for ESRGAN")
        else:
            # for all other models, post proc is same #
            prediction = prediction*255

        upscaled_patch = np.clip(prediction, 0, 255).astype(np.uint8)
        end =  time.time()
        print("postprocess Time: ", end-start)
       
    except Exception as e:
        print("Exception",str(e))
        return
    
    return upscaled_patch, elapsed_time

# Serve INDEX HTML file
@superRes_bp.route('/')
def index():
    return render_template('index.html')

# Endpoint for super resolution
@superRes_bp.route('/timer_string', methods=['POST'])
def timer_string():
    output_new = {
            "infertime": time_taken_model,
            "outputdims": upscaled_img_dims,
        }
    return jsonify(output_new), 200

# Endpoint for super resolution
@superRes_bp.route('/super_resolution', methods=['POST'])
def super_resolution():
    try:
    
        ## GETTING DATA FROM ELECTRON ##
        print("Fetching image data from the POST request")
        image_data = request.files['imageData']
        
        model_name = request.form['model_name']
        print("MODEL NAME:",model_name)
        
        runtime = request.form['runtime']
        print("RUN TIME:",runtime)
        
        print("load as PIL IMG")
        image_data = Image.open(image_data)
        #image_data.save("input_img.png")
        width, height = image_data.size
        print(f"Received img height = {height} ; width = {width}")
        
        
        ## MAKING CONNECTION WITH SNPE EXE ##
        context = zmq.Context()
        # Create a REQ (request) socket
        socket = context.socket(zmq.REQ)
        server_address = "tcp://localhost:5555"  # Replace with your server's address
        socket.connect(server_address)

        
        ## BUILDING NETWORK ##
        
        if model_name != globalvar.old_model_name or runtime != globalvar.old_runtime:
            print("___________________BUILDINGNETWORK________________")
            print("old_model_name: ", globalvar.old_model_name, "::model_name: ",model_name)
            print("old_runtime: ", globalvar.old_runtime, "::runtime: ",runtime)
            buildnetwork(socket, model_name, runtime)  ##build network when there is some change other than image
            globalvar.old_model_name = model_name
            globalvar.old_runtime = runtime 


        ## INFERENCING ON NETWORK ##
        
        
        # Step 0: Set upscaling params
        patch_size = 128
        overlap_factor = 0.1
        scaling_factor= 4
        
        
        # Step 1: Read Image and Extract 128x128 patches from the image
        image_np = np.array(image_data)

        # Dividing image into small patches
        emp = EMPatches()
        img_patches, indices = emp.extract_patches(image_np, patchsize=patch_size, overlap=overlap_factor)
        print(f"Num of patches of 128 = {len(img_patches)}")
        
        
        # Step 2: Upscale each patch by a factor of 4
        upscaled_patches= []
        infer_time_list = []
        time_taken = 0
        for patch in img_patches:
            pt, single_infer_time = upscale_patch(socket, patch, model_name, runtime)
            upscaled_patches.append(pt)
            time_taken = time_taken + single_infer_time  ##Adding time for all patches
            
        print("Received upscaled patches")
        
        global time_taken_model
        global upscaled_img_dims
        time_taken_model = str(f'{time_taken*1000:.2f}')+" ms"
        
        
        
        # Step 3: Stitch back the upscaled patches into a single image
        
        # Calculate the upscaled stiching indices
        up_img = np.zeros((image_np.shape[0]*scaling_factor, image_np.shape[1]*scaling_factor, image_np.shape[2]), np.uint8)
        _, new_indices = emp.extract_patches(up_img, patchsize=patch_size*scaling_factor, overlap=overlap_factor)
        
        # merge with new_indices
        merged_img = emp.merge_patches(upscaled_patches, new_indices, mode='min')
        upscaled_img_dims = str(merged_img.shape[1]) + " x " +str(merged_img.shape[0]);
        
        merged_img = Image.fromarray(np.uint8(merged_img))
        # merged_img.save("upscaled_model.png")
        
        # Convert the upscaled image to a binary response
        output_buffer = io.BytesIO()
        
        merged_img.save(output_buffer, format='PNG')
        
        print("Sending upscaled image as output to electron ...")
        output_buffer.seek(0)
        return send_file(output_buffer, mimetype='image/png')
 
    except Exception as e:
        print("#############EXCEPTION####################")
        print(str(e))
        return jsonify({'error': str(e)}), 400
