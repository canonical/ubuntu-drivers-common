import os
cwd = os.getcwd()
inputFile = os.path.join(cwd, "xorg.conf")
outputDir = cwd
inputDir = cwd.replace("tests", "quirks")