#!/usr/bin/env python

## Copyright 2009-2020 Intel Corporation
## SPDX-License-Identifier: Apache-2.0

from __future__ import print_function
import sys
import os
import platform
from glob import glob
import shutil
import tarfile
from zipfile import ZipFile
import re
import argparse

if sys.version_info[0] >= 3:
  from urllib.request import urlretrieve
else:
  from urllib import urlretrieve

MSVC_VERSION       = '15 2017'
ICC_VERSION        = '18.0'
ISPC_VERSION       = '1.12.0'
ISPC_VERSION_LINUX = '1.12.0b'
TBB_VERSION        = '2020.1'

def run(command):
  if os.system(command) != 0:
    raise Exception('non-zero return value')

def download_file(url, output_dir):
  print('Downloading file:', url)
  filename = os.path.join(output_dir, os.path.basename(url))
  urlretrieve(url, filename=filename)
  return filename

def extract_package(filename, output_dir):
  print('Extracting package:', filename)
  #shutil.unpack_archive(filename, output_dir)
  if re.search(r'(\.tar(\..+)?|tgz)$', filename):
    package = tarfile.open(filename)
  elif filename.endswith('.zip'):
    package = ZipFile(filename)
  else:
    raise Exception('unsupported package format')
  package.extractall(output_dir)
  package.close()

def create_package(filename, input_dir):
  print('Creating package:', filename)
  if filename.endswith('.tar.gz'):
    with tarfile.open(filename, "w:gz") as package:
      package.add(input_dir, arcname=os.path.basename(input_dir))
  elif filename.endswith('.zip'):
    shutil.make_archive(filename[:-4], 'zip', os.path.dirname(input_dir), os.path.basename(input_dir))
  else:
    raise Exception('unsupported package format')

def check_symbols(filename, label, max_version):
  with os.popen("nm \"%s\" | tr ' ' '\n' | grep @@%s_" % (filename, label)) as out:
    for line in out:
      symbol = line.strip()
      _, version = symbol.split('@@')
      _, version = version.split('_')
      version = [int(v) for v in version.split('.')]
      if version > list(max_version):
        raise Exception('problematic symbol %s in %s' % (symbol, os.path.basename(filename)))

def check_symbols_linux(filename):
  print('Checking symbols:', filename)
  check_symbols(filename, 'GLIBC',   (2, 17, 0))
  check_symbols(filename, 'GLIBCXX', (3, 4, 19))
  check_symbols(filename, 'CXXABI',  (1, 3, 7))

def main():
  # Detect the OS
  OS = {'Windows' : 'windows', 'Linux' : 'linux', 'Darwin' : 'macos'}[platform.system()]

  # Parse the arguments
  compilers = {'windows' : ['msvc', 'icc'],
               'linux'   : ['gcc', 'clang', 'icc'],
               'macos'   : ['clang', 'icc']}

  parser = argparse.ArgumentParser()
  parser.usage = '\rIntel(R) Open Image Denoise - Release\n' + parser.format_usage()
  parser.add_argument('stage', type=str, nargs='*', choices=['build', 'package'], default='build')
  parser.add_argument('--compiler', type=str, choices=compilers[OS], default='icc')
  parser.add_argument('--config', type=str, choices=['Debug', 'Release', 'RelWithDebInfo'], default='Release')
  cfg = parser.parse_args()

  # Set the directories
  root_dir = os.getcwd()
  deps_dir = os.path.join(root_dir, 'deps')
  if not os.path.isdir(deps_dir):
    os.makedirs(deps_dir)
  build_dir = os.path.join(root_dir, 'build_' + cfg.config.lower())

  # Build
  if 'build' in cfg.stage:
    # Set up ISPC
    ispc_release = 'ispc-v%s-' % ISPC_VERSION
    ispc_release += {'windows' : 'windows', 'linux' : 'linux', 'macos' : 'macOS'}[OS]
    ispc_dir = os.path.join(deps_dir, ispc_release)
    if not os.path.isdir(ispc_dir):
      # Download and extract ISPC
      ispc_url = 'https://github.com/ispc/ispc/releases/download/v%s/' % ISPC_VERSION
      ispc_url += 'ispc-v%s-linux' % ISPC_VERSION_LINUX if OS == 'linux' else ispc_release
      ispc_url += '.zip' if OS == 'windows' else '.tar.gz'
      ispc_filename = download_file(ispc_url, deps_dir)
      extract_package(ispc_filename, deps_dir)
      os.remove(ispc_filename)
    ispc_executable = os.path.join(ispc_dir, 'bin', 'ispc')

    # Set up TBB
    tbb_release = 'tbb-%s-' % TBB_VERSION
    tbb_release += {'windows' : 'win', 'linux' : 'lin', 'macos' : 'mac'}[OS]
    tbb_dir = os.path.join(deps_dir, tbb_release)
    if not os.path.isdir(tbb_dir):
      # Download and extract TBB
      tbb_url = 'https://github.com/oneapi-src/oneTBB/releases/download/v%s/%s' % (TBB_VERSION, tbb_release)
      tbb_url += '.zip' if OS == 'windows' else '.tgz'
      tbb_filename = download_file(tbb_url, deps_dir)
      os.makedirs(tbb_dir)
      extract_package(tbb_filename, tbb_dir)
      os.remove(tbb_filename)
    tbb_root = os.path.join(tbb_dir, 'tbb')

    # Create a clean build directory
    if os.path.isdir(build_dir):
      shutil.rmtree(build_dir)
    os.mkdir(build_dir)
    os.chdir(build_dir)

    if OS == 'windows':
      # Set up the compiler
      toolchain = 'Intel C++ Compiler %s' % ICC_VERSION if cfg.compiler == 'icc' else ''

      # Configure
      run('cmake -L ' +
          '-G "Visual Studio %s Win64" ' % MSVC_VERSION +
          '-T "%s" ' % toolchain +
          '-D ISPC_EXECUTABLE="%s.exe" ' % ispc_executable +
          '-D TBB_ROOT="%s" ' % tbb_root +
          '..')

      # Build
      run('cmake --build . --config %s --target ALL_BUILD' % cfg.config)
    else:
      # Set up the compiler
      cc = cfg.compiler
      cxx = {'gcc' : 'g++', 'clang' : 'clang++', 'icc' : 'icpc'}[cc]
      if cfg.compiler == 'icc':
        icc_dir = os.environ.get('OIDN_ICC_DIR_' + OS.upper())
        if icc_dir:
          cc  = os.path.join(icc_dir, cc)
          cxx = os.path.join(icc_dir, cxx)

      # Configure
      run('cmake -L ' +
          '-D CMAKE_C_COMPILER:FILEPATH="%s" ' % cc +
          '-D CMAKE_CXX_COMPILER:FILEPATH="%s" ' % cxx +
          '-D CMAKE_BUILD_TYPE=%s ' % cfg.config +
          '-D ISPC_EXECUTABLE="%s" ' % ispc_executable +
          '-D TBB_ROOT="%s" ' % tbb_root +
          '..')

      # Build
      run('cmake --build . --target preinstall -j -v')
    
  # Package
  if 'package' in cfg.stage:
    os.chdir(build_dir)

    # Configure
    run('cmake -L -D OIDN_ZIP_MODE=ON ..')

    # Build
    if OS == 'windows':
      run('cmake --build . --config %s --target PACKAGE' % cfg.config)
    else:
      run('cmake --build . --target package -j -v')

    # Extract the package
    package_filename = glob(os.path.join(build_dir, 'oidn-*'))[0]
    extract_package(package_filename, build_dir)
    package_dir = re.sub(r'\.(tar(\..*)?|zip)$', '', package_filename)

    # Get the list of binaries
    binaries = glob(os.path.join(package_dir, 'bin', '*'))
    if OS != 'windows':
      binaries += glob(os.path.join(package_dir, 'lib', '*.so*'))
    binaries = list(filter(lambda f: os.path.isfile(f) and not os.path.islink(f), binaries))

    # Check the symbols in the binaries
    if OS == 'linux':
      for f in binaries:
        check_symbols_linux(f)

    # Sign the binaries
    sign_file = os.environ.get('OIDN_SIGN_FILE_' + OS.upper())
    if sign_file:
      for f in binaries:
        run('%s -q -vv %s' % (sign_file, f))

      # Repack
      os.remove(package_filename)
      create_package(package_filename, package_dir)

    # Delete the extracted package
    shutil.rmtree(package_dir)

if __name__ == '__main__':
  main()
  