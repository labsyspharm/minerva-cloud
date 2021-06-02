from setuptools import setup, find_packages


def main():
    packages = find_packages()
    print("Installing `minerva-cloud` packages:\n", '\n'.join(packages))
    extras_require = {'test': ['moto']}
    extras_require['all'] = list({dep for deps in extras_require.values()
                                  for dep in deps})
    setup(name='minerva_cloud',
          version='0.0.1',
          description='Minerva Cloud',
          long_description='A package for managing the clound infrastructure '
                           'for Minerva.',
          url='https://github.com/labsyspharm/minerva-cloud',
          packages=packages,
          include_package_data=True,
          install_requires=['boto3', 'click', 'sqlalchemy', 'ruamel.yaml'],
          extras_require=extras_require,
          entry_points="""
          [console_scripts]
          minerva-cloud=cli:minerva_cloud
          """)


if __name__ == '__main__':
    main()
