#!/usr/bin/python

from setuptools import setup

setup(
    name="blus",
    version="0.0.2",
    description="Simple Bluez D-Bus client interface",
    url="https://github.com/molobrakos/blus",
    license="",
    author="Erik",
    author_email="error.errorsson@gmail.com",
    packages=[],
    install_requires=list(open("requirements.txt").read().strip().split("\n"))
)
