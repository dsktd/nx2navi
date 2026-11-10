// vram-hog <MiB>: holds that much device-local memory on the first Vulkan GPU until killed, to fill the card in lab
// runs (#141: does a full card fault by itself?). Build: tools/vram-hog.sh.
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <vulkan/vulkan.h>

int main(int argc, char **argv) {
    int mib = argc > 1 ? atoi(argv[1]) : 4096;
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VkInstance inst;
    if (vkCreateInstance(&ici, NULL, &inst)) return fprintf(stderr, "vram-hog: no instance\n"), 1;
    uint32_t n = 1;
    VkPhysicalDevice pd;
    vkEnumeratePhysicalDevices(inst, &n, &pd);
    float prio = 1;
    VkDeviceQueueCreateInfo q = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueCount = 1, .pQueuePriorities = &prio};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &q};
    VkDevice dev;
    if (vkCreateDevice(pd, &dci, NULL, &dev)) return fprintf(stderr, "vram-hog: no device\n"), 1;
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    uint32_t t = 0;
    while (t < mp.memoryTypeCount && mp.memoryTypes[t].propertyFlags != VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) t++;
    int got = 0;
    for (; got < mib; got += 256) {
        VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = 256u << 20, .memoryTypeIndex = t};
        VkDeviceMemory m;
        if (vkAllocateMemory(dev, &ai, NULL, &m)) break;
    }
    printf("vram-hog: holding %d MiB\n", got);
    fflush(stdout);
    pause();
    return 0;
}
