"""
    Minimalistic vulkan triangle example powered by asyncio. The demo
    was tested and should run on Windows and Linux. 
    For more information see the readme of the project.
    This is (kind of) a port of https://github.com/SaschaWillems/Vulkan

    To run this demo call:  
    ``python triangle.py``

    @author: Gabriel Dubé
"""
import platform, asyncio, vk, weakref
from ctypes import cast, c_char_p, c_uint, pointer, POINTER, byref, c_float, Structure
from xmath import *
from os.path import dirname

system_name = platform.system()
if system_name == 'Windows':
    from win32 import Win32Window as Window, WinSwapchain as BaseSwapchain
elif system_name == 'Linux':
    from xlib import XlibWindow as Window, XlibSwapchain as BaseSwapchain
else:
    raise OSError("Platform not supported")

# Whether to enable validation layer or not
ENABLE_VALIDATION = False

class Vertex(Structure):
    _fields_ = (('pos', c_float*3), ('col', c_float*3))

class Debugger(object):

    def __init__(self, app):
        self.app = weakref.ref(app)
        self.callback_fn=None
        self.debug_report_callback = None

    @staticmethod
    def print_message(flags, object_type, object, location, message_code, layer, message, user_data):
        if flags & vk.DEBUG_REPORT_ERROR_BIT_EXT:
            _type = 'ERROR'
        elif flags & vk.DEBUG_REPORT_WARNING_BIT_EXT:
            _type = 'WARNING'

        print("{}: {}".format(_type, message[::].decode()))
        return 0

    def start(self):
        app = self.app()
        if app is None:
            raise RuntimeError('Application was freed')

        callback_fn = vk.fn_DebugReportCallbackEXT(Debugger.print_message)
        create_info = vk.DebugReportCallbackCreateInfoEXT(
            s_type=vk.STRUCTURE_TYPE_DEBUG_REPORT_CREATE_INFO_EXT,
            next=vk.NULL, 
            flags=vk.DEBUG_REPORT_ERROR_BIT_EXT | vk.DEBUG_REPORT_WARNING_BIT_EXT,
            callback=callback_fn,
            user_data=vk.NULL
        )

        debug_report_callback = vk.DebugReportCallbackEXT(0)
        result = app.CreateDebugReportCallbackEXT(app.instance, byref(create_info), vk.NULL, byref(debug_report_callback))

        self.callback_fn = callback_fn
        self.debug_report_callback = debug_report_callback

    def stop(self):
        app = self.app()
        if app is None:
            raise RuntimeError('Application was freed')

        app.DestroyDebugReportCallbackEXT(app.instance, self.debug_report_callback, vk.NULL)

class Swapchain(BaseSwapchain):

    def __init__(self, app):
        super().__init__(app)

        self.swapchain = None
        self.images = None
        self.views = None

    def create(self):
        app = self.app()

        # Get the physical device surface capabilities (properties and format)
        cap = vk.SurfaceCapabilitiesKHR()
        result = app.GetPhysicalDeviceSurfaceCapabilitiesKHR(app.gpu, self.surface, byref(cap))
        if result != vk.SUCCESS:
            raise RuntimeError('Failed to get surface capabilities')

        # Get the available present mode
        prez_count = c_uint(0)
        result = app.GetPhysicalDeviceSurfacePresentModesKHR(app.gpu, self.surface, byref(prez_count), cast(vk.NULL, POINTER(c_uint)))
        if result != vk.SUCCESS and prez_count.value > 0:
            raise RuntimeError('Failed to get surface presenting mode')
        
        prez = (c_uint*prez_count.value)()
        app.GetPhysicalDeviceSurfacePresentModesKHR(app.gpu, self.surface, byref(prez_count), cast(prez, POINTER(c_uint)) )

        if cap.current_extent.width == -1:
            # If the surface size is undefined, the size is set to the size of the images requested
            width, height = app.window.dimensions()
            swapchain_extent = vk.Extent2D(width=width, height=height)
        else:
            # If the surface size is defined, the swap chain size must match
            # The client most likely uses windowed mode
            swapchain_extent = cap.current_extent
            width = swapchain_extent.width
            height = swapchain_extent.height

        # Prefer mailbox mode if present, it's the lowest latency non-tearing present  mode
        present_mode = vk.PRESENT_MODE_FIFO_KHR
        if vk.PRESENT_MODE_MAILBOX_KHR in prez:
            present_mode = vk.PRESENT_MODE_MAILBOX_KHR
        elif vk.PRESENT_MODE_IMMEDIATE_KHR in prez:
            present_mode = vk.PRESENT_MODE_IMMEDIATE_KHR

        # Get the number of images
        swapchain_image_count = cap.min_image_count + 1
        if cap.max_image_count > 0 and swapchain_image_count > cap.max_image_count:
            swapchain_image_count = cap.max_image_count

        # Default image transformation (use identity if supported)
        transform = cap.current_transform
        if cap.supported_transforms & vk.SURFACE_TRANSFORM_IDENTITY_BIT_KHR != 0:
            transform = vk.SURFACE_TRANSFORM_IDENTITY_BIT_KHR

        # Get the supported image format
        format_count = c_uint(0)
        result = app.GetPhysicalDeviceSurfaceFormatsKHR(app.gpu, self.surface, byref(format_count), cast(vk.NULL, POINTER(vk.SurfaceFormatKHR)))
        if result != vk.SUCCESS and format_count.value > 0:
            raise RuntimeError('Failed to get surface available image format')

        formats = (vk.SurfaceFormatKHR*format_count.value)()
        app.GetPhysicalDeviceSurfaceFormatsKHR(app.gpu, self.surface, byref(format_count), cast(formats, POINTER(vk.SurfaceFormatKHR)))

        # If the surface format list only includes one entry with VK_FORMAT_UNDEFINED,
		# there is no preferered format, so we assume VK_FORMAT_B8G8R8A8_UNORM
        if format_count == 1 and formats[0].format == vk.FORMAT_UNDEFINED:
            color_format = vk.FORMAT_B8G8R8A8_UNORM
        else:
            # Else select the first format
            color_format = formats[0].format

        app.formats['color'] = color_format
        color_space = formats[0].color_space

        #Create the swapchain
        create_info = vk.SwapchainCreateInfoKHR(
            s_type=vk.STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, next=vk.NULL, 
            flags=0, surface=self.surface, min_image_count=swapchain_image_count,
            image_format=color_format, image_color_space=color_space, 
            image_extent=swapchain_extent, image_array_layers=1, image_usage=vk.IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
            image_sharing_mode=vk.SHARING_MODE_EXCLUSIVE, queue_family_index_count=0,
            queue_family_indices=cast(vk.NULL, POINTER(c_uint)), pre_transform=transform, 
            composite_alpha=vk.COMPOSITE_ALPHA_OPAQUE_BIT_KHR, present_mode=present_mode,
            clipped=1,
            old_swapchain=(self.swapchain or vk.SwapchainKHR(0))
        )

        swapchain = vk.SwapchainKHR(0)
        result = app.CreateSwapchainKHR(app.device, byref(create_info), vk.NULL, byref(swapchain))
        
        if result == vk.SUCCESS:
            if self.swapchain is not None: #Destroy the old swapchain if it exists
                self.destroy_swapchain()
            self.swapchain = swapchain
            self.create_images(swapchain_image_count, color_format)
        else:
            raise RuntimeError('Failed to create the swapchain')
        
    def create_images(self, req_image_count, color_format):
        app = self.app()

        image_count = c_uint(0)
        result = app.GetSwapchainImagesKHR(app.device, self.swapchain, byref(image_count), vk.NULL_CUINT_PTR)
        if result != vk.SUCCESS and req_image_count != image_count.value:
            raise RuntimeError('Failed to get the swapchain images')
 
        self.images = (vk.Image * image_count.value)()
        self.views = (vk.ImageView * image_count.value)()

        assert( app.GetSwapchainImagesKHR(app.device, self.swapchain, byref(image_count), cast(self.images, POINTER(c_uint))) == vk.SUCCESS)

        for index, image in enumerate(self.images):
            components = vk.ComponentMapping(
                r=vk.COMPONENT_SWIZZLE_R, g=vk.COMPONENT_SWIZZLE_G,
                b=vk.COMPONENT_SWIZZLE_B, a=vk.COMPONENT_SWIZZLE_A,
            )

            subresource_range = vk.ImageSubresourceRange(
                aspect_mask=vk.IMAGE_ASPECT_COLOR_BIT, base_mip_level=0,
                level_count=1, base_array_layer=0, layer_count=1,
            )

            view_create_info = vk.ImageViewCreateInfo(
                s_type=vk.STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
                next=vk.NULL, flags=0, image=image,
                view_type=vk.IMAGE_VIEW_TYPE_2D, format=color_format,
                components=components, subresource_range=subresource_range
            )

            app.set_image_layout(
                app.setup_buffer, image, 
                vk.IMAGE_ASPECT_COLOR_BIT,
                vk.IMAGE_LAYOUT_UNDEFINED,
                vk.IMAGE_LAYOUT_PRESENT_SRC_KHR)

            view = vk.ImageView(0)
            result = app.CreateImageView(app.device, byref(view_create_info), vk.NULL, byref(view))
            if result == vk.SUCCESS:
                self.views[index] = view
            else:
                raise RuntimeError('Failed to create an image view.')

    def destroy_swapchain(self):
        app = self.app()
        for view in self.views:
            app.DestroyImageView(app.device, view, vk.NULL)
        app.DestroySwapchainKHR(app.device, self.swapchain, vk.NULL)

    def destroy(self):
        app = self.app()
        if self.swapchain is not None:
            self.destroy_swapchain()
        app.DestroySurfaceKHR(app.instance, self.surface, vk.NULL)
        


class Application(object):

    def create_instance(self):
        """
            Setup the vulkan instance
        """
        app_info = vk.ApplicationInfo(
            s_type=vk.STRUCTURE_TYPE_APPLICATION_INFO, next=vk.NULL,
            application_name=b'PythonText', application_version=0,
            engine_name=b'test', engine_version=0, api_version=((1<<22) | (0<<12) | (0))
        )

        if system_name == 'Windows':
            extensions = [b'VK_KHR_surface', b'VK_KHR_win32_surface']
        else:
            extensions = [b'VK_KHR_surface', b'VK_KHR_xcb_surface']

        if ENABLE_VALIDATION:
            extensions.append(b'VK_EXT_debug_report')
            layer_count = 1
            layer_names = [c_char_p(b'VK_LAYER_LUNARG_standard_validation')]
            _layer_names = cast((c_char_p*1)(*layer_names), POINTER(c_char_p))
        else:
            layer_count = 0
            _layer_names = vk.NULL_LAYERS

        extensions = [c_char_p(x) for x in extensions]
        _extensions = cast((c_char_p*len(extensions))(*extensions), POINTER(c_char_p))

        create_info = vk.InstanceCreateInfo(
            s_type=vk.STRUCTURE_TYPE_INSTANCE_CREATE_INFO, next=vk.NULL, flags=0,
            application_info=pointer(app_info), 

            enabled_layer_count=layer_count,
            enabled_layer_names=_layer_names,

            enabled_extension_count=len(extensions),
            enabled_extension_names=_extensions
        )

        instance = vk.Instance(0)
        result = vk.CreateInstance(byref(create_info), vk.NULL, byref(instance))
        if result == vk.SUCCESS:
            vk.load_instance_functions(self, instance)
            self.instance = instance

            # Start logging errors if validation is enabled
            if ENABLE_VALIDATION:
                self.debugger.start()

        else:
            raise RuntimeError('Instance creation failed. Error code: {}'.format(result))

    def create_device(self):
        self.gpu = None
        self.main_queue_family = None

        # Enumerate the physical devices
        gpu_count = c_uint(0)
        result = self.EnumeratePhysicalDevices(self.instance, byref(gpu_count), vk.NULL_HANDLE_PTR )
        if result != vk.SUCCESS or gpu_count.value == 0:
            raise RuntimeError('Could not fetch the physical devices or there are no devices available')

        buf = (vk.PhysicalDevice*gpu_count.value)()
        self.EnumeratePhysicalDevices(self.instance, byref(gpu_count), cast(buf, POINTER(vk.PhysicalDevice)))


        # For this example use the first available device
        self.gpu = vk.PhysicalDevice(buf[0])

        # Find a graphic queue that supports graphic operation and presentation into
        # the surface previously created
        queue_families_count = c_uint(0)
        self.GetPhysicalDeviceQueueFamilyProperties(
            self.gpu,
            byref(queue_families_count),
            cast(vk.NULL, POINTER(vk.QueueFamilyProperties))
        )
        
        if queue_families_count.value == 0:
            raise RuntimeError('No queues families found for the default GPU')

        queue_families = (vk.QueueFamilyProperties*queue_families_count.value)()
        self.GetPhysicalDeviceQueueFamilyProperties(
            self.gpu,
            byref(queue_families_count),
            cast(queue_families, POINTER(vk.QueueFamilyProperties))
        )

        surface = self.swapchain.surface
        supported = vk.c_uint(0)
        for index, queue in enumerate(queue_families):
            self.GetPhysicalDeviceSurfaceSupportKHR(self.gpu, index, surface, byref(supported))
            if queue.queue_flags & vk.QUEUE_GRAPHICS_BIT != 0 and supported.value == 1:
                self.main_queue_family = index
                break

        if self.main_queue_family is None:
            raise OSError("Could not find a queue that supports graphics and presenting")

        # Create the device
        priorities = (c_float*1)(0.0)
        queue_create_info = vk.DeviceQueueCreateInfo(
            s_type=vk.STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            next=vk.NULL,
            flags=0,
            queue_family_index=self.main_queue_family,
            queue_count=1,
            queue_priorities=priorities
        )

        queue_create_infos = (vk.DeviceQueueCreateInfo*1)(*(queue_create_info,))

        extensions = (b'VK_KHR_swapchain',)
        _extensions = cast((c_char_p*len(extensions))(*extensions), POINTER(c_char_p))
        
        if ENABLE_VALIDATION:
            layer_count = 1
            layer_names = (b'VK_LAYER_LUNARG_standard_validation',)
            _layer_names = cast((c_char_p*1)(*layer_names), POINTER(c_char_p))
        else:
            layer_count=0
            _layer_names=vk.NULL_LAYERS

        create_info = vk.DeviceCreateInfo(
            s_type=vk.STRUCTURE_TYPE_DEVICE_CREATE_INFO, next=vk.NULL, flags=0,
            queue_create_info_count=1, queue_create_infos=queue_create_infos,
            
            enabled_layer_count=layer_count, 
            enabled_layer_names=_layer_names,

            enabled_extension_count=1,
            enabled_extension_names=_extensions,

            enabled_features=vk.NULL
        )

        device = vk.Device(0)
        result = self.CreateDevice(self.gpu, byref(create_info), vk.NULL, byref(device))
        if result == vk.SUCCESS:
            vk.load_device_functions(self, device, self.GetDeviceProcAddr)
            self.device = device
        else:
            print(vk.c_int(result))
            raise RuntimeError('Could not create device.')

        
        # Get the physical device memory properties.
        self.gpu_mem = vk.PhysicalDeviceMemoryProperties()
        self.GetPhysicalDeviceMemoryProperties(self.gpu, byref(self.gpu_mem))

        # Get the queue that was created with the device
        queue = vk.Queue(0)
        self.GetDeviceQueue(device, self.main_queue_family, 0, byref(queue))
        if queue.value != 0:
            self.queue = queue
        else:
            raise RuntimeError("Could not get device queue")

    def create_swapchain(self):
        self.swapchain = Swapchain(self)

    def create_command_pool(self):
        create_info = vk.CommandPoolCreateInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, next= vk.NULL,
            flags=vk.COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
            queue_family_index=self.main_queue_family
        )

        pool = vk.CommandPool(0)
        result = self.CreateCommandPool(self.device, byref(create_info), vk.NULL, byref(pool))
        if result == vk.SUCCESS:
            self.cmd_pool = pool
        else:
            raise RuntimeError('Could not create command pool')

    def create_setup_buffer(self):
        create_info = vk.CommandBufferAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, next=vk.NULL, 
            command_pool=self.cmd_pool,
            level=vk.COMMAND_BUFFER_LEVEL_PRIMARY,
            command_buffer_count=1
        )
        begin_info = vk.CommandBufferBeginInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            next=vk.NULL, flags= 0, inheritance_info=vk.NULL
        )

        if self.setup_buffer is not None:
            self.FreeCommandBuffers(self.device, self.cmd_pool, 1, byref(self.setup_buffer))
            self.setup_buffer = None

        buffer = vk.CommandBuffer(0)
        result = self.AllocateCommandBuffers(self.device, byref(create_info), byref(buffer))
        if result == vk.SUCCESS:
            self.setup_buffer = buffer
        else:
            raise RuntimeError('Failed to create setup buffer')

        if self.BeginCommandBuffer(buffer, byref(begin_info)) != vk.SUCCESS:
            raise RuntimeError('Failed to start recording in the setup buffer')

    def create_command_buffers(self):
        # Create one command buffer per frame buffer
        # in the swap chain
        # Command buffers store a reference to the
        # frame buffer inside their render pass info
        # so for static usage without having to rebuild
        # them each frame, we use one per frame buffer
        image_count = len(self.swapchain.images)
        draw_buffers = (vk.CommandBuffer*image_count)()
        post_present_buffers = (vk.CommandBuffer*image_count)()

        alloc_info = vk.CommandBufferAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, next=vk.NULL,
            command_pool=self.cmd_pool,
            level=vk.COMMAND_BUFFER_LEVEL_PRIMARY,
            command_buffer_count=image_count
        )

        result = self.AllocateCommandBuffers(self.device, byref(alloc_info), cast(draw_buffers, POINTER(vk.CommandBuffer)))
        if result == vk.SUCCESS:
            self.draw_buffers = draw_buffers
        else:
            raise RuntimeError('Failed to drawing buffers')


        result = self.AllocateCommandBuffers(self.device, byref(alloc_info), cast(post_present_buffers, POINTER(vk.CommandBuffer)))
        if result == vk.SUCCESS:
            self.post_present_buffers = post_present_buffers
        else:
            raise RuntimeError('Failed to present buffers')
    
    def create_depth_stencil(self):
        width, height = self.window.dimensions()

        # Find a supported depth format
        depth_format = None
        depth_formats = (
            vk.FORMAT_D32_SFLOAT_S8_UINT,
            vk.FORMAT_D32_SFLOAT,
            vk.FORMAT_D24_UNORM_S8_UINT,
            vk.FORMAT_D16_UNORM_S8_UINT,
            vk.FORMAT_D16_UNORM,
        )

        format_props = vk.FormatProperties()
        for format in depth_formats:
            self.GetPhysicalDeviceFormatProperties(self.gpu, format, byref(format_props));
            if format_props.optimal_tiling_features & vk.FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT != 0:
                depth_format = format
                break

        if depth_format is None:
            raise RuntimeError('Could not find a valid depth format')

        create_info = vk.ImageCreateInfo(
            s_type=vk.STRUCTURE_TYPE_IMAGE_CREATE_INFO, next=vk.NULL, flags=0,
            image_type=vk.IMAGE_TYPE_2D, format=depth_format,
            extent=vk.Extent3D(width, height, 1), mip_levels=1,
            array_layers=1, samples=vk.SAMPLE_COUNT_1_BIT, tiling=vk.IMAGE_TILING_OPTIMAL,
            usage=vk.IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | vk.IMAGE_USAGE_TRANSFER_SRC_BIT,
        )

        subres_range = vk.ImageSubresourceRange(
            aspect_mask=vk.IMAGE_ASPECT_DEPTH_BIT, base_mip_level=0,
            level_count=1, base_array_layer=0, layer_count=1,
        )

        create_view_info = vk.ImageViewCreateInfo(
            s_type=vk.STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, next=vk.NULL,
            flags=0, view_type=vk.IMAGE_VIEW_TYPE_2D, format=depth_format,
            subresource_range=subres_range
        )

        mem_alloc_info = vk.MemoryAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, next=vk.NULL,
            allocation_size=0, memory_type_index=0
        )

        depthstencil_image = vk.Image(0)
        result=self.CreateImage(self.device, byref(create_info), vk.NULL, byref(depthstencil_image))
        if result != vk.SUCCESS:
            raise RuntimeError('Failed to create depth stencil image')

        memreq = vk.MemoryRequirements()
        self.GetImageMemoryRequirements(self.device, depthstencil_image, byref(memreq))
        mem_alloc_info.allocation_size = memreq.size
        mem_alloc_info.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_DEVICE_LOCAL_BIT)[1]
        
        depthstencil_mem = vk.DeviceMemory(0)
        result = self.AllocateMemory(self.device, byref(mem_alloc_info), vk.NULL, byref(depthstencil_mem))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not allocate depth stencil image memory')

        result = self.BindImageMemory(self.device, depthstencil_image, depthstencil_mem, 0)
        if result != vk.SUCCESS:
            raise RuntimeError('Could not bind the depth stencil memory to the image')
            
        self.set_image_layout(
            self.setup_buffer, depthstencil_image,
            vk.IMAGE_ASPECT_DEPTH_BIT | vk.IMAGE_ASPECT_STENCIL_BIT,
            vk.IMAGE_LAYOUT_UNDEFINED,
            vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL
        )

        depthstencil_view = vk.ImageView(0)
        create_view_info.image = depthstencil_image
        result = self.CreateImageView(self.device, byref(create_view_info), vk.NULL, byref(depthstencil_view))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not create image view for depth stencil')
            
        self.formats['depth'] = depth_format
        self.depth_stencil['image'] = depthstencil_image
        self.depth_stencil['mem'] = depthstencil_mem
        self.depth_stencil['view'] = depthstencil_view

    def create_renderpass(self):
        color, depth = vk.AttachmentDescription(), vk.AttachmentDescription()

        #Color attachment
        color.format = self.formats['color']
        color.samples = vk.SAMPLE_COUNT_1_BIT
        color.load_op = vk.ATTACHMENT_LOAD_OP_CLEAR
        color.store_op = vk.ATTACHMENT_STORE_OP_STORE
        color.stencil_load_op = vk.ATTACHMENT_LOAD_OP_DONT_CARE
        color.stencil_store_op = vk.ATTACHMENT_STORE_OP_DONT_CARE
        color.initial_layout = vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL
        color.final_layout = vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL

        #Depth attachment
        depth.format = self.formats['depth']
        depth.samples = vk.SAMPLE_COUNT_1_BIT
        depth.load_op = vk.ATTACHMENT_LOAD_OP_CLEAR
        depth.store_op = vk.ATTACHMENT_STORE_OP_STORE
        depth.stencil_load_op = vk.ATTACHMENT_LOAD_OP_DONT_CARE
        depth.stencil_store_op = vk.ATTACHMENT_STORE_OP_DONT_CARE
        depth.initial_layout = vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL
        depth.final_layout = vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL


        color_ref = vk.AttachmentReference( attachment=0, layout=vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL )
        depth_ref = vk.AttachmentReference( attachment=1, layout=vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL )

        subpass = vk.SubpassDescription(
            pipeline_bind_point = vk.PIPELINE_BIND_POINT_GRAPHICS,
            flags = 0, input_attachment_count=0, input_attachments=vk.NULL_REF,
            color_attachment_count=1, color_attachments=pointer(color_ref),
            resolve_attachments=vk.NULL_REF, depth_stencil_attachment=pointer(depth_ref),
            preserve_attachment_count=0, preserve_attachments=cast(vk.NULL, POINTER(c_uint))
        )

        attachments = (vk.AttachmentDescription*2)(color, depth)
        create_info = vk.RenderPassCreateInfo(
            s_type=vk.STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
            next=vk.NULL, flags=0, attachment_count=2,
            attachments=cast(attachments, POINTER(vk.AttachmentDescription)),
            subpass_count=1, subpasses=pointer(subpass), dependency_count=0,
            dependencies=vk.NULL
        )

        renderpass = vk.RenderPass(0)
        result = self.CreateRenderPass(self.device, byref(create_info), vk.NULL, byref(renderpass))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not create renderpass')

        self.render_pass = renderpass

    def create_pipeline_cache(self):
        create_info = vk.PipelineCacheCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO, next=vk.NULL,
            flags=0, initial_data_size=0, initial_data=vk.NULL
        )

        pipeline_cache = vk.PipelineCache(0)
        result = self.CreatePipelineCache(self.device, byref(create_info), vk.NULL, byref(pipeline_cache))
        if result != vk.SUCCESS:
            raise RuntimeError('Failed to create pipeline cache')

        self.pipeline_cache = pipeline_cache

    def create_framebuffers(self):
        attachments = cast((vk.ImageView*2)(), POINTER(vk.ImageView))
        attachments[1] = self.depth_stencil['view']
        

        width, height = self.window.dimensions()

        create_info = vk.FramebufferCreateInfo(
            s_type=vk.STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
            next=vk.NULL, flags=0, render_pass=self.render_pass,
            attachment_count=2, attachments=attachments,
            width=width, height=height, layers=1
        )

        self.framebuffers = (vk.Framebuffer*len(self.swapchain.images))()
        for index, view in enumerate(self.swapchain.views):
            fb = vk.Framebuffer(0)
            attachments[0] = view

            result = self.CreateFramebuffer(self.device, byref(create_info), vk.NULL, byref(fb))
            if result != vk.SUCCESS:
                raise RuntimeError('Could not create the framebuffers')
            
            self.framebuffers[index] = fb

    def flush_setup_buffer(self):
        if self.EndCommandBuffer(self.setup_buffer) != vk.SUCCESS:
            raise RuntimeError('Failed to end setup command buffer')

        submit_info = vk.SubmitInfo(
            s_type=vk.STRUCTURE_TYPE_SUBMIT_INFO, next=vk.NULL,
            wait_semaphore_count=0, wait_semaphores=vk.NULL_HANDLE_PTR,
            wait_dst_stage_mask=vk.NULL_CUINT_PTR, command_buffer_count=1,
            command_buffers=pointer(self.setup_buffer),
            signal_semaphore_count=0, signal_semaphores=vk.NULL_HANDLE_PTR,
        )

        result = self.QueueSubmit(self.queue, 1, byref(submit_info), 0)
        if result != vk.SUCCESS:
            raise RuntimeError("Setup buffer sumbit failed")
        
        result = self.QueueWaitIdle(self.queue)
        if result != vk.SUCCESS:
            raise RuntimeError("Setup execution failed")

        self.FreeCommandBuffers(self.device, self.cmd_pool, 1, byref(self.setup_buffer))
        self.setup_buffer = None

    def set_image_layout(self, cmd, image, aspect_mask, old_layout, new_layout, subres=None):
        
        if subres is None:
            subres = vk.ImageSubresourceRange(
                aspect_mask=aspect_mask, base_mip_level=0,
                level_count=1, base_array_layer=0, layer_count=1,
            )

        barrier = vk.ImageMemoryBarrier(
            s_type=vk.STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, next=vk.NULL, 
            old_layout=old_layout, new_layout=new_layout,
            src_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
            dst_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
            image=image, subresource_range=subres
        )

        # Source layouts mapping (old)
        old_map = {
            vk.IMAGE_LAYOUT_PREINITIALIZED: vk.ACCESS_HOST_WRITE_BIT | vk.ACCESS_TRANSFER_WRITE_BIT,
            vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL: vk.ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT,
            vk.IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL: vk.ACCESS_TRANSFER_READ_BIT,
            vk.IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL: vk.ACCESS_SHADER_READ_BIT
        }
        if old_layout in old_map.values():
            barrier.src_access_mask = old_map[old_layout]
        else:
            barrier.src_access_mask = 0

        # Target layouts
        if new_layout == vk.IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL:
            barrier.dst_access_mask = vk.ACCESS_TRANSFER_WRITE_BIT

        elif new_layout == vk.IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL:
            barrier.src_access_mask |= vk.ACCESS_TRANSFER_READ_BIT
            barrier.dst_access_mask = vk.ACCESS_TRANSFER_READ_BIT

        elif new_layout == vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL:
            barrier.dst_access_mask = vk.ACCESS_COLOR_ATTACHMENT_WRITE_BIT
            barrier.src_access_mask = vk.ACCESS_TRANSFER_READ_BIT

        elif new_layout == vk.IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL:
            barrier.dst_access_mask |= vk.ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT
        
        elif new_layout == vk.IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL:
            barrier.src_access_mask = vk.ACCESS_HOST_WRITE_BIT | vk.ACCESS_TRANSFER_WRITE_BIT
            barrier.dst_access_mask = vk.ACCESS_SHADER_READ_BIT

        self.CmdPipelineBarrier(
            cmd,
            vk.PIPELINE_STAGE_TOP_OF_PIPE_BIT,
            vk.PIPELINE_STAGE_TOP_OF_PIPE_BIT,
            0,
            0,vk.NULL,
            0,vk.NULL,
            1, byref(barrier)
        )

    def get_memory_type(self, bits, properties):
        for index, mem_t in enumerate(self.gpu_mem.memory_types):
            if (bits & 1) == 1:
                if mem_t.property_flags & properties == properties:
                    return (True, index)
            bits >>= 1

        return (False, None)

    def load_shader(self, name, stage):
        # Read the shader data
        path = './shaders/{}'.format(name)
        shader_f = open(path, 'rb')
        shader_bin = shader_f.read()
        shader_bin_size = len(shader_bin)
        shader_bin = (vk.c_ubyte*shader_bin_size)(*shader_bin)
        shader_f.close()

        # Compile the shader
        module = vk.ShaderModule(0)
        module_create_info = vk.ShaderModuleCreateInfo(
            s_type=vk.STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, next=vk.NULL,
            code_size=len(shader_bin), code=cast(shader_bin, POINTER(c_uint))
        )

        result = self.CreateShaderModule(self.device, byref(module_create_info), vk.NULL, byref(module))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not compile shader at {}'.format(path))

        shader_info = vk.PipelineShaderStageCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, next=vk.NULL,
            flags=0, stage=stage, module=module, name=b'main',
            specialization_info=vk.NULL
        )

        self.shaders_modules.append(module)
        return shader_info

    def resize_display(self, width, height):
        if not self.initialized:
            return 

        self.create_setup_buffer()

        # Recreate the swap chain
        self.swapchain.create()

        # Recreate the frame buffers
        self.DestroyImageView(self.device, self.depth_stencil['view'], vk.NULL)
        self.DestroyImage(self.device, self.depth_stencil['image'], vk.NULL)
        self.FreeMemory(self.device, self.depth_stencil['mem'], vk.NULL)
        self.create_depth_stencil()

        for fb in self.framebuffers:
            self.DestroyFramebuffer(self.device, fb, vk.NULL)
        self.create_framebuffers()

        self.flush_setup_buffer()

        # Command buffers need to be recreated as they may store
	    # references to the recreated frame buffer
        len_draw_buffers = len(self.draw_buffers)
        self.FreeCommandBuffers(self.device, self.cmd_pool, len_draw_buffers, cast(self.draw_buffers, POINTER(vk.CommandBuffer)))
        self.FreeCommandBuffers(self.device, self.cmd_pool, len_draw_buffers, cast(self.post_present_buffers, POINTER(vk.CommandBuffer)))
        self.create_command_buffers()

    def __init__(self):
        self.initialized = False
        self.running = False
        self.zoom = -2.5               # Scene zoom
        self.rotation = (c_float*3)()  # Scene rotation
        self.shaders_modules = []      # A list of compiled shaders. GC'ed with the application
        self.debugger = Debugger(self) # Throw errors if validations layers are activated

        # Syncronization between the system events and the rendering
        self.rendering_done = asyncio.Event()

        #System window
        self.window = Window(self)

        # Vulkan objets
        self.gpu = None
        self.gpu_mem = None
        self.instance = None
        self.device = None
        self.queue = None
        self.swapchain = None
        self.cmd_pool = None
        self.setup_buffer = None
        self.draw_buffers = []  
        self.post_present_buffers = []
        self.render_pass = None
        self.pipeline_cache = None
        self.framebuffers = None
        self.depth_stencil = {'image':None, 'mem':None, 'view':None}
        self.formats = {'color':None, 'depth':None}
        
        # Vulkan objets initialization
        self.create_instance()
        self.create_swapchain()
        self.create_device()
        self.create_command_pool()

        self.create_setup_buffer()
        self.swapchain.create()
        self.create_command_buffers()
        self.create_depth_stencil()
        self.create_renderpass()
        self.create_pipeline_cache()
        self.create_framebuffers()
        self.flush_setup_buffer()


        self.window.show()

    def __del__(self):
        if self.instance is None:
            return

        dev = self.device
        if dev is not None:
            if self.swapchain is not None:
                self.swapchain.destroy()

            if self.setup_buffer is not None:
                self.FreeCommandBuffers(dev, self.cmd_pool, 1, byref(self.setup_buffer))

            len_draw_buffers = len(self.draw_buffers)
            if len_draw_buffers > 0:
                self.FreeCommandBuffers(dev, self.cmd_pool, len_draw_buffers, cast(self.draw_buffers, POINTER(vk.CommandBuffer)))
                self.FreeCommandBuffers(dev, self.cmd_pool, len_draw_buffers, cast(self.post_present_buffers, POINTER(vk.CommandBuffer)))

            if self.render_pass is not None:
                self.DestroyRenderPass(self.device, self.render_pass, vk.NULL)

            for mod in self.shaders_modules:
                self.DestroyShaderModule(self.device, mod, vk.NULL)
            
            if self.framebuffers is not None:
                for fb in self.framebuffers:
                    self.DestroyFramebuffer(self.device, fb, vk.NULL)

            if self.depth_stencil['view'] is not None:
                self.DestroyImageView(dev, self.depth_stencil['view'], vk.NULL)

            if self.depth_stencil['image'] is not None:
                self.DestroyImage(dev, self.depth_stencil['image'], vk.NULL)

            if self.depth_stencil['mem'] is not None:
                self.FreeMemory(dev, self.depth_stencil['mem'], vk.NULL)
            
            if self.pipeline_cache:
                self.DestroyPipelineCache(self.device, self.pipeline_cache, vk.NULL)

            if self.cmd_pool:
                self.DestroyCommandPool(dev, self.cmd_pool, vk.NULL)

        
            self.DestroyDevice(dev, vk.NULL)

        if ENABLE_VALIDATION:
            self.debugger.stop()

        self.DestroyInstance(self.instance, vk.NULL)
        print('Application freed!')


class TriangleApplication(Application):

    VERTEX_BUFFER_BIND_ID = 0

    def create_semaphores(self):
        create_info = vk.SemaphoreCreateInfo(
            s_type=vk.STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,
            next=vk.NULL, flags=0
        )

        present = vk.Semaphore(0)
        render = vk.Semaphore(0)

        result1 = self.CreateSemaphore(self.device, byref(create_info), vk.NULL, byref(present))
        result2 = self.CreateSemaphore(self.device, byref(create_info), vk.NULL, byref(render))
        if vk.SUCCESS not in (result1, result2):
            raise RuntimeError('Failed to create the semaphores')

        self.render_semaphores['present'] = present
        self.render_semaphores['render'] = render

    def describe_bindings(self):
        bindings = (vk.VertexInputBindingDescription*1)()
        attributes = (vk.VertexInputAttributeDescription*2)()

        bindings[0].binding = self.VERTEX_BUFFER_BIND_ID
        bindings[0].stride = vk.sizeof(Vertex)
        bindings[0].input_rate = vk.VERTEX_INPUT_RATE_VERTEX
        

        # Attribute descriptions
		# Describes memory layout and shader attribute locations

        # Location 0: Position
        attributes[0].binding = self.VERTEX_BUFFER_BIND_ID
        attributes[0].location = 0
        attributes[0].format = vk.FORMAT_R32G32B32_SFLOAT
        attributes[0].offset = 0

        # Location 1: Color
        attributes[1].binding = self.VERTEX_BUFFER_BIND_ID
        attributes[1].location = 1
        attributes[1].format = vk.FORMAT_R32G32B32_SFLOAT
        attributes[1].offset = vk.sizeof(c_float)*3

        self.triangle['bindings'] = bindings
        self.triangle['attributes'] = attributes

    def create_triangle(self):
        data = vk.c_void_p(0)
        memreq = vk.MemoryRequirements()
        memalloc = vk.MemoryAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, next=vk.NULL,
            allocation_size=0, memory_type_index=0
        )

        # Setup vertices
        vertices_data = (Vertex*3)(
            Vertex(pos=(1.0, 1.0, 0.0), col=(1.0, 0.0,0.0)),
            Vertex(pos=(-1.0, 1.0, 0.0), col=(0.0, 1.0,0.0)),
            Vertex(pos=(0.0, -1.0, 0.0), col=(0.0, 0.0,1.0)),
        )

        vertices_size = vk.sizeof(Vertex)*3

        # Setup indices
        indices_data = (c_uint*3)(0,1,2)
        indices_size = vk.sizeof(indices_data)

        #
        # Store the vertices in the device memory
        #

        # 1 Create a staging buffer
        vertex = {'buffer': vk.Buffer(0), 'memory': vk.DeviceMemory(0)}
        indices = {'buffer': vk.Buffer(0), 'memory': vk.DeviceMemory(0)}

        # 2 Create the vertex buffer
        vertex_info = vk.BufferCreateInfo(
            s_type=vk.STRUCTURE_TYPE_BUFFER_CREATE_INFO, next=vk.NULL,
            flags=0, size=vertices_size, usage=vk.BUFFER_USAGE_TRANSFER_SRC_BIT,
            sharing_mode=0, queue_family_index_count=0, queue_family_indices=vk.NULL_CUINT_PTR
        )

        result = self.CreateBuffer(self.device, byref(vertex_info), vk.NULL, byref(vertex['buffer']))
        if result != vk.SUCCESS:
            raise 'Could not create a buffer'

        # 3 Allocate memory for the vertex buffer
        self.GetBufferMemoryRequirements(self.device, vertex['buffer'], byref(memreq))
        memalloc.allocation_size = memreq.size
        memalloc.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_HOST_VISIBLE_BIT)[1]
        result = self.AllocateMemory(self.device, byref(memalloc), vk.NULL, byref(vertex['memory']))
        if result != vk.SUCCESS:
            raise 'Could not allocate buffer memory'

        # 4  Map the buffer memory and write the data
        result = self.MapMemory(self.device, vertex['memory'], 0, memalloc.allocation_size, 0, byref(data))
        if result != vk.SUCCESS:
            raise 'Could not map memory to local'
        vk.memmove(data, vertices_data, vertices_size)
        x = cast(data, POINTER(c_float))
        self.UnmapMemory(self.device, vertex['memory'])

        # 5 Bind the memory and the buffer together
        result = self.BindBufferMemory(self.device, vertex['buffer'], vertex['memory'], 0)
        if result != vk.SUCCESS:
            raise 'Could not bind buffer memory'

        # 6 Create a destination buffer with device only visibility and allocate its memory
        vertex_info.usage = vk.BUFFER_USAGE_VERTEX_BUFFER_BIT | vk.BUFFER_USAGE_TRANSFER_DST_BIT
        result = self.CreateBuffer(self.device, byref(vertex_info), vk.NULL, byref(self.triangle['buffer']))
        if result != vk.SUCCESS:
            raise 'Could not create triangle buffer'

        # 7 Allocate the buffer memory and bind the allocated memory to the buffer
        self.GetBufferMemoryRequirements(self.device, self.triangle['buffer'], byref(memreq))
        memalloc.allocation_size = memreq.size
        memalloc.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_DEVICE_LOCAL_BIT)[1]
        result = self.AllocateMemory(self.device, byref(memalloc), vk.NULL, self.triangle['memory'])
        if result != vk.SUCCESS:
            raise 'Could not allocate the triangle memory'
        result = self.BindBufferMemory(self.device, self.triangle['buffer'], self.triangle['memory'], 0)
        if result != vk.SUCCESS:
            raise 'Could not bind the triangle memory'

        #
        # Store the indices in the device memory
        #

        # Same steps as 1,2,3,4,5
        indices_info = vertex_info
        indices_info.size = indices_size
        indices_info.usage = vk.BUFFER_USAGE_TRANSFER_SRC_BIT

        assert(self.CreateBuffer(self.device, byref(indices_info), vk.NULL, byref(indices['buffer'])) == vk.SUCCESS)
        self.GetBufferMemoryRequirements(self.device, indices['buffer'], byref(memreq))
        memalloc.allocation_size = memreq.size
        memalloc.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_HOST_VISIBLE_BIT)[1]
        assert(self.AllocateMemory(self.device, byref(memalloc), vk.NULL, byref(indices['memory'])) == vk.SUCCESS)
        assert(self.MapMemory(self.device, indices['memory'], 0, indices_size, 0, byref(data)) == vk.SUCCESS)
        vk.memmove(data , indices_data, indices_size)
        self.UnmapMemory(self.device, indices['memory'])
        assert(self.BindBufferMemory(self.device, indices['buffer'], indices['memory'], 0) == vk.SUCCESS)
        
        # Same steps as 5, 7 (with the exception for the usage flags)
        indices_info.usage =  vk.BUFFER_USAGE_INDEX_BUFFER_BIT | vk.BUFFER_USAGE_TRANSFER_DST_BIT
        assert(self.CreateBuffer(self.device, byref(indices_info), vk.NULL, self.triangle['indices_buffer']) == vk.SUCCESS)
        self.GetBufferMemoryRequirements(self.device, self.triangle['indices_buffer'], byref(memreq))
        memalloc.allocation_size = memreq.size
        memalloc.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_DEVICE_LOCAL_BIT)[1]
        assert(self.AllocateMemory(self.device, byref(memalloc), vk.NULL, byref(self.triangle['indices_memory']))==vk.SUCCESS)
        assert(self.BindBufferMemory(self.device, self.triangle['indices_buffer'], self.triangle['indices_memory'], 0) ==vk.SUCCESS)
       
        # Copy the staging buffer memory into the final buffers
        cmd_info = vk.CommandBufferAllocateInfo(
            s_type = vk.STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            command_pool=self.cmd_pool,
            level=vk.COMMAND_BUFFER_LEVEL_PRIMARY,
            command_buffer_count=1
        )
        begin_info = vk.CommandBufferBeginInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, next=vk.NULL,
            flags=0, inheritance_info=vk.NULL
        )
        copy_region = vk.BufferCopy(src_offset=0, dst_offset=0, size=0)
        copy_command = vk.CommandBuffer(0)

        assert(self.AllocateCommandBuffers(self.device, byref(cmd_info), byref(copy_command)) == vk.SUCCESS)
        assert(self.BeginCommandBuffer(copy_command, byref(begin_info)) == vk.SUCCESS)
        
        #Vertex Buffer
        copy_region.size = vertices_size
        self.CmdCopyBuffer(
            copy_command, vertex['buffer'],
            self.triangle['buffer'],
            1,
            byref(copy_region)
        )

        #Index Buffer
        copy_region.size = indices_size
        self.CmdCopyBuffer(
            copy_command, indices['buffer'],
            self.triangle['indices_buffer'],
            1,
            byref(copy_region)
        )

        assert(self.EndCommandBuffer(copy_command) == vk.SUCCESS)

        # Submit commands to the queue
        submit_info = vk.SubmitInfo(
            s_type=vk.STRUCTURE_TYPE_SUBMIT_INFO, next=vk.NULL,
            wait_semaphore_count=0, wait_semaphores=vk.NULL_HANDLE_PTR,
            wait_dst_stage_mask=vk.NULL_CUINT_PTR, command_buffer_count=1,
            command_buffers=pointer(copy_command),
            signal_semaphore_count=0, signal_semaphores=vk.NULL_HANDLE_PTR,
        )

        assert(self.QueueSubmit(self.queue, 1, byref(submit_info), 0)==vk.SUCCESS)
        assert(self.QueueWaitIdle(self.queue)==vk.SUCCESS)

        # Free temporary ressources
        self.FreeCommandBuffers(self.device, self.cmd_pool, 1, byref(copy_command))

        self.DestroyBuffer(self.device, vertex['buffer'], vk.NULL)
        self.FreeMemory(self.device, vertex['memory'], vk.NULL)

        self.DestroyBuffer(self.device, indices['buffer'], vk.NULL)
        self.FreeMemory(self.device, indices['memory'], vk.NULL)

        self.describe_bindings()

    def create_uniform_buffers(self):
        memreq = vk.MemoryRequirements()

        # Vertex shader uniform buffer block
        buffer_info = vk.BufferCreateInfo(
            s_type=vk.STRUCTURE_TYPE_BUFFER_CREATE_INFO, next=vk.NULL,
            flags=0, size=vk.sizeof(Mat4)*3, usage=vk.BUFFER_USAGE_UNIFORM_BUFFER_BIT,
            sharing_mode=0, queue_family_index_count=0, queue_family_indices=vk.NULL_CUINT_PTR
        )

        alloc_info = vk.MemoryAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, next=vk.NULL,
            allocation_size=0, memory_type_index=0
        )

        result = self.CreateBuffer(self.device, byref(buffer_info), vk.NULL, self.uniform_data['buffer'])
        if result != vk.SUCCESS:
            raise RuntimeError('Could not create the uniform buffer')

        self.GetBufferMemoryRequirements(self.device, self.uniform_data['buffer'], byref(memreq))
        alloc_info.allocation_size = memreq.size
        alloc_info.memory_type_index = self.get_memory_type(memreq.memory_type_bits, vk.MEMORY_PROPERTY_HOST_VISIBLE_BIT)[1]

        result = self.AllocateMemory(self.device, byref(alloc_info), vk.NULL, byref(self.uniform_data['memory']))
        if result != vk.SUCCESS:
            raise RuntimeError('Failed to allocate the uniform buffer memory')

        result = self.BindBufferMemory(self.device, self.uniform_data['buffer'], self.uniform_data['memory'], 0)
        if result != vk.SUCCESS:
            raise RuntimeError('Failed to bind the uniform buffer memory')

        # Store information in the uniform's descriptor
        self.uniform_data['descriptor'].buffer = self.uniform_data['buffer']
        self.uniform_data['descriptor'].offset = 0
        self.uniform_data['descriptor'].range = vk.sizeof(self.matrices)

        self.update_uniform_buffers()
 
    def create_descriptor_set_layout(self):
        # Setup layout of descriptors used in this example
		# Basically connects the different shader stages to descriptors
		# for binding uniform buffers, image samplers, etc.
		# So every shader binding should map to one descriptor set layout
		# binding

        # Binding 0 : Uniform buffer (Vertex shader)
        binding = vk.DescriptorSetLayoutBinding(
            descriptor_type=vk.DESCRIPTOR_TYPE_UNIFORM_BUFFER,
            descriptor_count=1, stage_flags=vk.SHADER_STAGE_VERTEX_BIT,
            immutable_samplers=vk.NULL_HANDLE_PTR
        )

        layout = vk.DescriptorSetLayoutCreateInfo(
            s_type=vk.STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
            next=vk.NULL, flags=0, binding_count=1, bindings=pointer(binding)
        )

        ds_layout = vk.DescriptorSetLayout(0)
        result = self.CreateDescriptorSetLayout(self.device, byref(layout), vk.NULL, byref(ds_layout))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not create descriptor set layout')

        # Create the pipeline layout that is used to generate the rendering pipelines that
		# are based on this descriptor set layout
		# In a more complex scenario you would have different pipeline layouts for different
		# descriptor set layouts that could be reused
        pipeline_info = vk.PipelineLayoutCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, next=vk.NULL,
            flags=0, set_layout_count=1, set_layouts=pointer(ds_layout),
            push_constant_range_count=0
        )

        pipeline_layout = vk.PipelineLayout(0)
        result = self.CreatePipelineLayout(self.device, byref(pipeline_info), vk.NULL, byref(pipeline_layout))


        self.pipeline_layout = pipeline_layout
        self.descriptor_set_layout = ds_layout

    def create_pipeline(self):
        tri = self.triangle

        # Vertex input state
        input_state = vk.PipelineVertexInputStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO, next=vk.NULL, flags=0,
            vertex_binding_description_count = 1,
            vertex_attribute_description_count = 2,
            vertex_binding_descriptions = cast(tri['bindings'], POINTER(vk.VertexInputBindingDescription)),
            vertex_attribute_descriptions = cast(tri['attributes'], POINTER(vk.VertexInputAttributeDescription))
        )
        tri['input_state'] = input_state

        # Vertex input state
		# Describes the topoloy used with this pipeline 
        input_assembly_state = vk.PipelineInputAssemblyStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, next=vk.NULL,
            flags=0, primitive_restart_enable=0,
            topology=vk.PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,  #This pipeline renders vertex data as triangle lists
        )

        # Rasterization state
        raster_state = vk.PipelineRasterizationStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, next=vk.NULL,
            flags=0,
            polygon_mode=vk.POLYGON_MODE_FILL,          # Solid polygon mode
            cull_mode= vk.CULL_MODE_NONE,               # No culling
            front_face=vk.FRONT_FACE_CLOCKWISE,
            depth_clamp_enable=0, rasterizer_discard_enable=0,
            depth_bias_enable=0, line_width=1.0
        )

        # Color blend state
        # Describes blend modes and color masks
        blend_state = vk.PipelineColorBlendAttachmentState(
            color_write_mask=0xF, blend_enable=0
        )
        color_blend_state = vk.PipelineColorBlendStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, next=vk.NULL,
            flags=0, logic_op_enable=0, attachment_count=1, attachments=pointer(blend_state)
        )

        # Viewport state
        viewport_state = vk.PipelineViewportStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
            viewport_count=1, scissor_count=1
        )

        # Enable dynamic states
		# Describes the dynamic states to be used with this pipeline
		# Dynamic states can be set even after the pipeline has been created
		# So there is no need to create new pipelines just for changing
		# a viewport's dimensions or a scissor box
        dynamic_states = (c_uint*2)(vk.DYNAMIC_STATE_VIEWPORT, vk.DYNAMIC_STATE_SCISSOR)
        dynamic_state = vk.PipelineDynamicStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, next=vk.NULL,
            flags=0,dynamic_state_count=2,
            dynamic_states=cast(dynamic_states, POINTER(c_uint))
        )

        # Depth and stencil state
		# Describes depth and stenctil test and compare ops
        # Basic depth compare setup with depth writes and depth test enabled
		# No stencil used 
        op_state = vk.StencilOpState(
            fail_op=vk.STENCIL_OP_KEEP, pass_op=vk.STENCIL_OP_KEEP,
            compare_op=vk.COMPARE_OP_ALWAYS
        )
        depth_stencil_state = vk.PipelineDepthStencilStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO, next=vk.NULL, 
            flags=0, depth_test_enable=1, depth_write_enable=1, 
            depth_compare_op=vk.COMPARE_OP_LESS_OR_EQUAL,
            depth_bounds_test_enable=0, stencil_test_enable=0,
            front=op_state, back=op_state
        )

        # Multi sampling state
        # No multi sampling used in this example
        multisample_state = vk.PipelineMultisampleStateCreateInfo(
            s_type=vk.STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, next=vk.NULL, 
            flags=0, rasterization_samples=vk.SAMPLE_COUNT_1_BIT
        )

        # Load shaders
		# Shaders are loaded from the SPIR-V format, which can be generated from glsl
        shader_stages = (vk.PipelineShaderStageCreateInfo * 2)(
            self.load_shader('triangle.vert.spv', vk.SHADER_STAGE_VERTEX_BIT),
            self.load_shader('triangle.frag.spv', vk.SHADER_STAGE_FRAGMENT_BIT)
        )

        create_info = vk.GraphicsPipelineCreateInfo(
            s_type=vk.STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, next=vk.NULL,
            flags=0, stage_count=2, 
            stages=cast(shader_stages, POINTER(vk.PipelineShaderStageCreateInfo)),
            vertex_input_state=pointer(input_state),
            input_assembly_state=pointer(input_assembly_state),
            tessellation_state=vk.NULL,
            viewport_state=pointer(viewport_state),
            rasterization_state=pointer(raster_state),
            multisample_state=pointer(multisample_state),
            depth_stencil_state=pointer(depth_stencil_state),
            color_blend_state=pointer(color_blend_state),
            dynamic_state=pointer(dynamic_state),
            layout=self.pipeline_layout,
            render_pass=self.render_pass,
            subpass=0,
            basePipelineHandle=vk.Pipeline(0),
            basePipelineIndex=0
        )

        pipeline = vk.Pipeline(0)
        result = self.CreateGraphicsPipelines(self.device, self.pipeline_cache, 1, byref(create_info), vk.NULL, byref(pipeline))
        if result != vk.SUCCESS:
             raise RuntimeError('Failed to create the graphics pipeline')
        
        self.pipeline = pipeline

    def create_descriptor_pool(self):

        # We need to tell the API the number of max. requested descriptors per type
        # This example only uses one descriptor type (uniform buffer) and only
		# requests one descriptor of this type
        type_counts = vk.DescriptorPoolSize(
            type=vk.DESCRIPTOR_TYPE_UNIFORM_BUFFER,
            descriptor_count=1
        )

        # Create the global descriptor pool
		# All descriptors used in this example are allocated from this pool
        pool_create_info = vk.DescriptorPoolCreateInfo(
            s_type=vk.STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, next=vk.NULL,
            flags=0, pool_size_count=1, pool_sizes=pointer(type_counts),
            max_sets=1  
        )

        pool = vk.DescriptorPool(0)
        result = self.CreateDescriptorPool(self.device, byref(pool_create_info), vk.NULL, byref(pool))

        self.descriptor_pool = pool

    def create_descriptor_set(self):
        # Update descriptor sets determining the shader binding points
		# For every binding point used in a shader there needs to be one
		# descriptor set matching that binding point

        descriptor_alloc = vk.DescriptorSetAllocateInfo(
            s_type=vk.STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, next=vk.NULL,
            descriptor_pool=self.descriptor_pool, descriptor_set_count=1,
            set_layouts=pointer(self.descriptor_set_layout)
        )

        descriptor_set = vk.DescriptorSet(0)
        result = self.AllocateDescriptorSets(self.device, byref(descriptor_alloc), byref(descriptor_set))
        if result != vk.SUCCESS:
            raise RuntimeError('Could not allocate descriptor set')


        #Binding 0 : Uniform buffer
        write_set = vk.WriteDescriptorSet(
            s_type=vk.STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, next=vk.NULL,
            dst_set=descriptor_set, descriptor_count=1,
            descriptor_type=vk.DESCRIPTOR_TYPE_UNIFORM_BUFFER,
            buffer_info=pointer(self.uniform_data['descriptor']),
            dst_binding=0 # Binds this uniform buffer to binding point 0
        )

        self.UpdateDescriptorSets(self.device, 1, byref(write_set), 0, vk.NULL)
        self.descriptor_set = descriptor_set

    def init_command_buffers(self):
        
        begin_info = vk.CommandBufferBeginInfo(
            s_type=vk.STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, next=vk.NULL
        )

        clear_values = (vk.ClearValue*2)()
        clear_values[0].color = vk.ClearColorValue((c_float*4)(0.1, 0.1, 0.1, 1.0))
        clear_values[1].depth_stencil = vk.ClearDepthStencilValue(depth=1.0, stencil=0)

        width, height = self.window.dimensions()
        render_area = vk.Rect2D(
            offset=vk.Offset2D(x=0, y=0),
            extent=vk.Extent2D(width=width, height=height)
        )
        render_pass_begin = vk.RenderPassBeginInfo(
            s_type=vk.STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, next=vk.NULL,
            render_pass=self.render_pass, render_area=render_area,
            clear_value_count=2, 
            clear_values = cast(clear_values, POINTER(vk.ClearValue))
        )

        for index, cmdbuf in enumerate(self.post_present_buffers):
            assert(self.BeginCommandBuffer(cmdbuf, byref(begin_info)) == vk.SUCCESS)

            subres = vk.ImageSubresourceRange(
                aspect_mask=vk.IMAGE_ASPECT_COLOR_BIT, base_mip_level=0,
                level_count=1, base_array_layer=0, layer_count=1,
            )

            barrier = vk.ImageMemoryBarrier(
                s_type=vk.STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, next=vk.NULL,
                src_access_mask=0,
                dst_access_mask=vk.ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
                old_layout=vk.IMAGE_LAYOUT_PRESENT_SRC_KHR,
                new_layout=vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                src_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
                dst_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
                image=self.swapchain.images[index], 
                subresource_range=subres
            )

            self.CmdPipelineBarrier(
				cmdbuf, 
				vk.PIPELINE_STAGE_ALL_COMMANDS_BIT, 
				vk.PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
				0,
				0, vk.NULL,
				0, vk.NULL,
				1, byref(barrier));

            assert(self.EndCommandBuffer(cmdbuf) == vk.SUCCESS)

        for index, cmdbuf in enumerate(self.draw_buffers):
            assert(self.BeginCommandBuffer(cmdbuf, byref(begin_info)) == vk.SUCCESS)

            render_pass_begin.framebuffer = self.framebuffers[index]
            self.CmdBeginRenderPass(cmdbuf, byref(render_pass_begin), vk.SUBPASS_CONTENTS_INLINE)

            # Update dynamic viewport state
            viewport = vk.Viewport(
                x=0.0, y=0.0, width=float(width), height=float(height),
                min_depth=0.0, max_depth=1.0
            )
            self.CmdSetViewport(cmdbuf, 0, 1, byref(viewport))

            # Update dynamic scissor state
            scissor = render_area
            self.CmdSetScissor(cmdbuf, 0, 1, byref(scissor))

            # Bind descriptor sets describing shader binding points
            self.CmdBindDescriptorSets(cmdbuf, vk.PIPELINE_BIND_POINT_GRAPHICS, self.pipeline_layout, 0, 1, byref(self.descriptor_set), 0, vk.NULL)

            # Bind the rendering pipeline (including the shaders)
            self.CmdBindPipeline(cmdbuf, vk.PIPELINE_BIND_POINT_GRAPHICS, self.pipeline)

            # Bind triangle vertices
            offsets = vk.c_ulonglong(0)
            self.CmdBindVertexBuffers(cmdbuf, self.VERTEX_BUFFER_BIND_ID, 1, byref(self.triangle['buffer']), byref(offsets))

            # Bind triangle indices
            self.CmdBindIndexBuffer(cmdbuf, self.triangle['indices_buffer'], 0, vk.INDEX_TYPE_UINT32)

            # Draw indexed triangle
            self.CmdDrawIndexed(cmdbuf, 3, 1, 0, 0, 1)

            self.CmdEndRenderPass(cmdbuf)

            # Add a present memory barrier to the end of the command buffer
			# This will transform the frame buffer color attachment to a
			# new layout for presenting it to the windowing system integration
            subres = vk.ImageSubresourceRange(
                aspect_mask=vk.IMAGE_ASPECT_COLOR_BIT, base_mip_level=0,
                level_count=1, base_array_layer=0, layer_count=1,
            )

            barrier = vk.ImageMemoryBarrier(
                s_type=vk.STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, next=vk.NULL,
                src_access_mask=vk.ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
                dst_access_mask=vk.ACCESS_MEMORY_READ_BIT,
                old_layout=vk.IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                new_layout=vk.IMAGE_LAYOUT_PRESENT_SRC_KHR,
                src_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
                dst_queue_family_index=vk.QUEUE_FAMILY_IGNORED,
                image=self.swapchain.images[index], 
                subresource_range=subres
            )

            self.CmdPipelineBarrier(
				cmdbuf, 
				vk.PIPELINE_STAGE_ALL_COMMANDS_BIT, 
				vk.PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
				0,
				0, vk.NULL,
				0, vk.NULL,
				1, byref(barrier));

            
            assert(self.EndCommandBuffer(cmdbuf) == vk.SUCCESS)

    def update_uniform_buffers(self):
        data = vk.c_void_p(0)
        matsize = vk.sizeof(Mat4)*3

        # Projection 
        width, height = self.window.dimensions()
        self.matrices[0].set_data(perspective(60.0, width/height, 0.1, 256.0))

        # Model
        mod_mat = rotate(None, self.rotation[0], (1.0, 0.0, 0.0))
        mod_mat = rotate(mod_mat, self.rotation[1], (0.0, 1.0, 0.0))
        self.matrices[1].set_data(rotate(mod_mat, self.rotation[2], (0.0, 0.0, 1.0)))

        # View
        self.matrices[2].set_data(translate(None, (0.0, 0.0, self.zoom)))


        self.MapMemory(self.device, self.uniform_data['memory'], 0, matsize, 0, byref(data))
        vk.memmove(data, self.matrices, matsize)
        self.UnmapMemory(self.device, self.uniform_data['memory'])

    def resize_display(self, width, height):
        if not self.initialized:
            return 
            
        Application.resize_display(self, width, height)

        self.init_command_buffers()
        self.QueueWaitIdle(self.queue)
        self.DeviceWaitIdle(self.device)

        self.update_uniform_buffers()

    def run(self):
        """
            Add the render phase to the asyncio loop
        """
        asyncio.ensure_future(self.render())
        self.initialized = True

    def draw(self):
        current_buffer = c_uint(0)

        #  Get next image in the swap chain (back/front buffer)
        result = self.AcquireNextImageKHR(
            self.device, self.swapchain.swapchain, vk.c_ulonglong(-1),
            self.render_semaphores['present'], vk.Fence(0), byref(current_buffer)
        )
        if result != vk.SUCCESS:
            raise Exception("Could not aquire next image from swapchain")

        cb = current_buffer.value

        prebuf = vk.CommandBuffer(self.post_present_buffers[cb])
        submit_info = vk.SubmitInfo(
            s_type=vk.STRUCTURE_TYPE_SUBMIT_INFO,
            command_buffer_count=1,
            command_buffers=pointer(prebuf)
        )
        assert(self.QueueSubmit(self.queue, 1, byref(submit_info), vk.Fence(0)) == vk.SUCCESS)
        assert(self.QueueWaitIdle(self.queue) == vk.SUCCESS)
        
        # The submit information structure contains a list of
		# command buffers and semaphores to be submitted to a queue
		# If you want to submit multiple command buffers, pass an array
        stages = c_uint(vk.PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT)
        drawbuf = vk.CommandBuffer(self.draw_buffers[cb])
        submit_info = vk.SubmitInfo(
            s_type=vk.STRUCTURE_TYPE_SUBMIT_INFO,
            wait_dst_stage_mask=pointer(stages),

            # The wait semaphore ensures that the image is presented 
		    # before we start submitting command buffers again
            wait_semaphore_count=1,
            wait_semaphores=pointer(self.render_semaphores['present']),

            # The signal semaphore is used during queue presentation
            # to ensure that the image is not rendered before all
            # commands have been submitted
            signal_semaphore_count=1,
            signal_semaphores=pointer(self.render_semaphores['render']),

            # Submit the currently active command buffer
            command_buffer_count=1, 
            command_buffers=pointer(drawbuf)
        )

        #Submit to the graphics queue
        assert(self.QueueSubmit(self.queue, 1, byref(submit_info), vk.Fence(0)) == vk.SUCCESS)

        # Present the current buffer to the swap chain
		# We pass the signal semaphore from the submit info
		# to ensure that the image is not rendered until
		# all commands have been submitted
        present_info = vk.PresentInfoKHR(
            s_type=vk.STRUCTURE_TYPE_PRESENT_INFO_KHR, next=vk.NULL,
            swapchain_count=1, swapchains=pointer(self.swapchain.swapchain),
            image_indices = pointer(current_buffer),
            wait_semaphores = pointer(self.render_semaphores['render']),
            wait_semaphore_count=1
        )
        
        result = self.QueuePresentKHR(self.queue, byref(present_info));
        if result != vk.SUCCESS:
            raise "Could not render the scene"


    async def render(self):
        """
            Render the scene
        """
        print("Running!")
        import time
        loop = asyncio.get_event_loop()
        frame_counter = 0
        fps_timer = 0.0
        self.running = True

        while self.running:
            t_start = loop.time()

            # draw
            self.DeviceWaitIdle(self.device)
            self.draw()
            self.DeviceWaitIdle(self.device)
            #time.sleep(1/30)
            
            frame_counter += 1
            t_end = loop.time()
            delta = t_end-t_start
            fps_timer += delta
            if fps_timer > 1:
                self.window.set_title('Triangle - {} fps'.format(frame_counter))
                frame_counter = 0
                fps_timer = 0.0


            await asyncio.sleep(0)
        

        self.rendering_done.set()

    def __init__(self):
        Application.__init__(self)

        self.pipeline_layout = None
        self.pipeline = None
        self.descriptor_set = None
        self.descriptor_set_layout = None
        self.descriptor_pool = None
        self.render_semaphores = {'present': None, 'render': None}
        self.matrices = (Mat4*3)(Mat4(), Mat4(), Mat4()) # 0: Projection, 1: Model, 2: View

        self.uniform_data = {
            'buffer': vk.Buffer(0),
            'memory': vk.DeviceMemory(0),
            'descriptor': vk.DescriptorBufferInfo()
        }

        self.triangle = {
            'buffer': vk.Buffer(0),
            'memory': vk.DeviceMemory(0),
            'indices_buffer': vk.Buffer(0),
            'indices_memory': vk.DeviceMemory(0),
            'bindings': None,
            'attributes': None,
            'input_state': None
        }

        self.create_semaphores()
        self.create_triangle()
        self.create_uniform_buffers()
        self.create_descriptor_set_layout()
        self.create_pipeline()
        self.create_descriptor_pool()
        self.create_descriptor_set()
        self.init_command_buffers()

    def __del__(self):
        if self.device is not None:
            self.DestroyDescriptorPool(self.device, self.descriptor_pool, vk.NULL)

            self.DestroyPipeline(self.device, self.pipeline, vk.NULL)

            self.DestroyPipelineLayout(self.device, self.pipeline_layout, vk.NULL)

            self.DestroyDescriptorSetLayout(self.device, self.descriptor_set_layout, vk.NULL)

            self.DestroyBuffer(self.device, self.triangle['buffer'], vk.NULL)
            self.FreeMemory(self.device, self.triangle['memory'], vk.NULL)

            self.DestroyBuffer(self.device, self.triangle['indices_buffer'], vk.NULL)
            self.FreeMemory(self.device, self.triangle['indices_memory'], vk.NULL)

            self.DestroyBuffer(self.device, self.uniform_data['buffer'], vk.NULL)
            self.FreeMemory(self.device, self.uniform_data['memory'], vk.NULL)

            self.DestroySemaphore(self.device, self.render_semaphores['present'], vk.NULL)
            self.DestroySemaphore(self.device, self.render_semaphores['render'], vk.NULL)

        Application.__del__(self)

def main():
    app = TriangleApplication()
    app.run()

    loop = asyncio.get_event_loop()
    loop.run_forever()

if __name__ == '__main__':
    main()