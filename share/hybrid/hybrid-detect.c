/* hybrid-detect:
 *
 * Detect which GPU in a hybrid graphics configuration should be
 * used
 *
 * Authored by:
 *   Alberto Milone
 *   Evan Broder
 * 
 * Copyright (C) 2011 Canonical Ltd
 * 
 * Based on code from ./hw/xfree86/common/xf86pciBus.c in xorg-server
 *
 * Copyright (c) 1997-2003 by The XFree86 Project, Inc.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE COPYRIGHT HOLDER(S) OR AUTHOR(S) BE LIABLE FOR ANY CLAIM, DAMAGES OR
 * OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
 * ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 *
 * Except as contained in this notice, the name of the copyright holder(s)
 * and author(s) shall not be used in advertising or otherwise to promote
 * the sale, use or other dealings in this Software without prior written
 * authorization from the copyright holder(s) and author(s).
 *
 *
 * Build with `gcc -o hybrid-detect hybrid-detect.c $(pkg-config --cflags --libs pciaccess)`
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pciaccess.h>

#define PCI_CLASS_PREHISTORIC           0x00

#define PCI_CLASS_DISPLAY               0x03

#define PCI_CLASS_MULTIMEDIA            0x04
#define PCI_SUBCLASS_MULTIMEDIA_VIDEO   0x00

#define PCI_CLASS_PROCESSOR             0x0b
#define PCI_SUBCLASS_PROCESSOR_COPROC   0x40

#define PCIINFOCLASSES(c)                                               \
    ( (((c) & 0x00ff0000) == (PCI_CLASS_PREHISTORIC << 16))             \
      || (((c) & 0x00ff0000) == (PCI_CLASS_DISPLAY << 16))              \
      || ((((c) & 0x00ffff00)                                           \
           == ((PCI_CLASS_MULTIMEDIA << 16) | (PCI_SUBCLASS_MULTIMEDIA_VIDEO << 8)))) \
      || ((((c) & 0x00ffff00)                                           \
           == ((PCI_CLASS_PROCESSOR << 16) | (PCI_SUBCLASS_PROCESSOR_COPROC << 8)))) )

#define FILENAME "/usr/share/nvidia-common/last_gfx_boot"

static struct pci_slot_match match = {
    PCI_MATCH_ANY, PCI_MATCH_ANY, PCI_MATCH_ANY, PCI_MATCH_ANY, 0
};

/* Get the output of a command */
char* get_output(char *command) {
    FILE *pfile = NULL;
    pfile = popen(command, "r");
    if (pfile == NULL) {
        fprintf(stderr, "Failed to run command\n");
        return NULL;
    }
    char temp[1035];
    char **full_output = NULL;
    char *output = NULL;
    full_output = (char**)calloc(1, sizeof(full_output));
    *full_output = "\0";

    while (fgets(temp, sizeof(temp)-1, pfile) != NULL) {
        asprintf(full_output, "%s", temp);
    }
    pclose(pfile);

    output = (char*)calloc(strlen(*full_output), sizeof(char));
    strcpy(output, *full_output);
    free(full_output);

    /* Remove newline */
    int len = strlen(output);
    if(output[len-1] == '\n' )
       output[len-1] = 0;

    return output;
}

/* Get the master link of an alternative */
char* get_alternative_link(char *arch_path, char *pattern) {
    char command[80];
    sprintf(command, "update-alternatives --list %s_gl_conf | grep %s",
            arch_path, pattern);
    char *alternative = NULL;
    alternative = get_output(command);

    return alternative;
}

int main(int argc, char *argv[]) {

    /* Check root privileges */
    uid_t uid=getuid();
    if (uid != 0) {
        fprintf(stderr, "Error: please run this program as root\n");
        exit(1);
    }
    
    pci_system_init();

    struct pci_device_iterator *iter = pci_slot_match_iterator_create(&match);
    if (!iter)
        return 1;

    FILE *pfile = NULL;
    int last_vendor = 0;
    int last_device = 0;
    char *arch_path = NULL;

    /* Read from last boot gfx */
    pfile = fopen(FILENAME, "r");
    if (pfile == NULL) {
        fprintf(stderr, "I couldn't open %s for reading.\n", FILENAME);
        /* Create the file for the 1st time */
        pfile = fopen(FILENAME, "w");
        printf("Create %s for the 1st time\n", FILENAME);
        if (pfile == NULL) {
            fprintf(stderr, "I couldn't open %s for writing.\n",
                    FILENAME);
            exit(1);
        }
        fprintf(pfile, "%x:%x\n", 0x0, 0x0);
        fflush(pfile);
        fclose(pfile);
        /* Try again */
        pfile = fopen(FILENAME, "r");
    }
    fscanf(pfile, "%x:%x\n", &last_vendor, &last_device);
    fclose(pfile);

    struct pci_device *info;
    while ((info = pci_device_next(iter)) != NULL) {
        if (PCIINFOCLASSES(info->device_class) &&
            pci_device_is_boot_vga(info)) {
            //printf("%x:%x\n", info->vendor_id, info->device_id);
            char *driver = NULL;
            if (info->vendor_id == 0x10de) {
                driver = "nvidia";
            }
            else if (info->vendor_id == 0x8086) {
                driver = "mesa";
            }
            else {
                fprintf(stderr, "No hybrid graphics cards detected\n");
                break;
            }

            pfile = fopen(FILENAME, "w");
            if (pfile == NULL) {
                fprintf(stderr, "I couldn't open %s for writing.\n",
                        FILENAME);
                exit(1);
            }
            fprintf(pfile, "%x:%x\n", info->vendor_id, info->device_id);
            fflush(pfile);
            fclose(pfile);

            if (last_vendor !=0 && last_vendor != info->vendor_id) {
                printf("Gfx was changed in the BIOS\n");
        
                char *arch = NULL;
                arch = get_output("dpkg --print-architecture");
                if (strcmp(arch, "amd64") == 0) {
                    arch_path = "x86_64-linux-gnu";
                }
                else if (strcmp(arch, "amd64") == 0) {
                    arch_path = "i386-linux-gnu";
                }
                else {
                    fprintf(stderr,
                            "%s is not supported for hybrid graphics\n",
                            arch);
                    free(arch);
                    break;
                }
                free(arch);

                char *alternative = NULL;
                alternative = get_alternative_link(arch_path, driver);
        
                if (alternative == NULL) {
                    fprintf(stderr, "Error: no alternative found\n");
                    break;
                }
                else {
                    /* Set the alternative */
                    printf("Select %s\n", alternative);
                    char command[200];
                    sprintf(command, "update-alternatives --set %s_gl_conf %s",
                            arch_path, alternative);
                    system(command);

                    /* call ldconfig */
                    system("LDCONFIG_NOTRIGGER=y ldconfig");

                    free(alternative);
                }
            }
            else {
                printf("No gfx change\n");
                break;
            }
            break;
        }
    }
    pci_iterator_destroy(iter);
    return 0;
}
