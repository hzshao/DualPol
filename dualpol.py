"""
Title/Version
-------------
Python Interface to Dual-Pol Radar Algorithms (DualPol)
DualPol v0.9
Developed & tested with Python 2.7 and 3.4
Last changed 09/02/2015


Author
------
Timothy Lang
NASA MSFC
timothy.j.lang@nasa.gov
(256) 961-7861


Overview
--------
This is an object-oriented Python module that facilitates precipitation
retrievals (e.g., hydrometeor type, precipitation rate, precipitation mass,
particle size distribution information) from polarimetric radar data. It
leverages existing open source radar software packages to perform all-in-one
retrievals that are then easily visualized or saved using existing software.

To access this module, add the following to your program and then make sure
the path to this script is in your PYTHONPATH:
import dualpol


Notes
-----
Dependencies: numpy, pyart, warnings, skewt, csu_radartools, matplotlib
Python 3 compliant SkewT here: https://github.com/tjlang/SkewT


Change Log
----------
v0.9 Major Changes (09/02/15):
1. Added QC capabilities, including filters for insects, high SDP, and speckles.
   These are based on the csu_radartools.csu_misc module. QC is performed prior
   to all retrievals, except for KDP calculations.

v0.8 Major Changes (08/07/15):
1. Now supports Python 3.4 and 2.7. Other versions untested.

v0.7 Major Changes (07/02/15):
1. Made code pep8 compliant

v0.6 Major Changes (05/21/15):
1. KDP calculation accepts gate spacing keyword (gs).
2. Adjusted sounding read to work with latest version of skewt
3. More info added to docstrings

v0.5 Major Changes (03/13/15):
1. KDP calculation implemented.
2. Moved keyword arguments to separate dictionary (kwargs) and implemented
   check_kwargs() function to process them.

v0.4 Major Changes (03/05/15):
1. DSD calculations implemented.
2. Project renamed to DualPol from RadBro.

v0.3 Major Changes (02/20/15):
1. Rainfall rate implemented

v0.2 Major Changes (01/27/15):
1. Ice/liquid mass calculations implemented.

v0.1 Functionality(01/26/15):
1. Summer HID calculations implemented.
2. Support for sounding import.

"""
from __future__ import print_function
import numpy as np
import warnings
import pyart
import matplotlib.colors as colors
from pyart.io.common import radar_coords_to_cart
from skewt import SkewT
from csu_radartools import (csu_fhc, csu_liquid_ice_mass, csu_blended_rain,
                            csu_dsd, csu_kdp, csu_misc)

VERSION = '0.9'
RNG_MULT = 1000.0
DEFAULT_WEIGHTS = csu_fhc.DEFAULT_WEIGHTS
BAD = -32768
DEFAULT_SDP = 12.0
DEFAULT_DZ_RANGE = csu_misc.DEFAULT_DZ_RANGE
DEFAULT_DR_THRESH = csu_misc.DEFAULT_DR_THRESH

#####################################

DEFAULT_KW = {'dz': 'DZ', 'dr': 'DR', 'dp': None, 'rh': 'RH',
              'kd': None, 'ld': None, 'sounding': None,
              'verbose': False, 'thresh_sdp': DEFAULT_SDP, 'fhc_T_factor': 1,
              'fhc_weights': DEFAULT_WEIGHTS, 'name_fhc': 'FH', 'band': 'S',
              'fhc_method': 'hybrid', 'kdp_method': 'CSU', 'bad': BAD,
              'use_temp': True, 'ice_flag': False, 'dsd_flag': True,
              'fhc_flag': True, 'rain_method': 'hidro', 'precip_flag': True,
              'liquid_ice_flag': True, 'winter': False, 'gs': 150.0,
              'qc_flag': False, 'kdp_window': 3.0,
              'dz_range': DEFAULT_DZ_RANGE, 'name_sdp': 'SDP_CSU',
              'thresh_dr': DEFAULT_DR_THRESH, 'speckle': 4}

kwargs = np.copy(DEFAULT_KW)

#####################################


class DualPolRetrieval(object):

    """
    Class that wraps all the dual-polarization retrievals powered by
    CSU_RadarTools.

    Brief overview of DualPolRetrieval structure
    --------------------------------------------
    Main attributes of interest is radar, which is the original Py-ART radar
    object provided to DualPolRetrieval. DualPolRetrieval.radar contains
    new fields based on what the user wanted DualPolRetrieval to do.

    New fields that can be in DualPolRetrieval.radar.fields:
    'FH' (or whatever user provided in name_fhc kwarg) = HID
    'FI' = Ice Fraction
    'ZDP' = Difference Reflectivity
    'KDP_CSU' = KDP as calculated by CSU_RadarTools
    'FDP_CSU' = Filtered differential phase
    'SDP_CSU' = Standard deviation of differential phase
    'MI' = Mass of ice
    'MW' = Mass of liquid water
    'rain' = Rainfall rate
    'method' = Rainfall method used
    'D0' = Median Volume Diameter
    'NW' = Normalized Intercept Parameter
    'MU' = Mu in Gamma DSD model
    """

    def __init__(self, radar, **kwargs):
        """
        Arguments
        ---------
        radar = Py-ART radar object

        Keywords
        --------
        dz = String name of reflectivity field
        dr = String name of differential reflectivity field
        kd = String name of specific differential phase field, if not provided
             it will be calculated using csu_radartools
        rh = String name of correlation coefficient field
        ld = String name of linear depolarization ratio field
        dp = String name of differential phase field
        sounding = Name of UWYO sounding file or 2xN array where:
                   sounding['z'] = Heights (km MSL), must be montonic
                   sounding['T'] = Temperatures (C)
        winter = Flag to note whether to use wintertime retrievals
        band = Radar frequency band letter ('C' or 'S' supported)
        verbose = Set to True to get text feedback
        thresh_sdp = Threshold on standard deviation of differential phase to
                     use on KDP calculation (if done)
        fhc_T_factor = Extra weighting on T to be used in HID calculations
        fhc_weights = Weights for variables in HID. Dictionary form, like so:
            {'DZ': 1.5, 'DR': 0.8, 'KD': 1.0, 'RH': 0.8, 'LD': 0.5, 'T': 0.4}
        name_fhc = Name to give HID field once calculated
        fhc_method = 'hybrid' or 'linear' methods; hybrid preferred
        kdp_method = 'CSU' currently supported
        bad = Value to provide bad data
        use_temp = Set to False to not consider T in HID calculations
        rain_method = Method to use to estimate rainfall. If not 'hidro', then
                      will use blended rainfall algorithm based on ZDP & ice
                      fraction. If 'hidro', then uses CSU_HIDRO approach.
        ice_flag = Set to True to return ice fraction and ZDP from CSU blended
                   rainfall algorithm and store them as radar object fields.
                   Only used if rain_method is not 'hidro'.
        dsd_flag = Set to False to not calculate DSD parameters
        fhc_flag = Set to False to not calculate HID
        precip_flag = Set to False to not calculate rainfall
        liquid_ice_flag = Set to False to not calculate liquid/ice mass
        gs = Gate spacing of the radar (meters). Only used if KDP is calculated
             using CSU_RadarTools.
        kdp_window = Window length (in km) used as basis for PHIDP filtering.
                     Only used if KDP is calculated using CSU_RadarTools.
        name_sdp = Name of field holding (or that will hold) the SDP data.
        qc_flag = Set to true to filter the data for insects, high SDP
                  (set by thresh_sdp keyword), and speckles. Will permanently
                  change the reflectivity field's mask, and by extension affect
                  all retrieved fields' masks.
        dz_range = Used by the insect filter. A list of 2-element tuples.
                   Within each DZ range represented by a tuple, the ZDR
                   threshold in dr_thresh (see below) will be applied.
        thresh_dr = List of thresholds on ZDR to be applied within a given
                    element of dz_range (see above).
        speckle = Number of contiguous gates or less for an element to be
                  considered a speckle.
        """
        # Set radar fields
        kwargs = check_kwargs(kwargs, DEFAULT_KW)
        self.verbose = kwargs['verbose']
        flag = self.do_radar_check(radar)
        if not flag:
            return
        self.name_dz = kwargs['dz']
        self.name_dr = kwargs['dr']
        self.name_kd = kwargs['kd']
        self.name_rh = kwargs['rh']
        self.name_ld = kwargs['ld']
        self.name_dp = kwargs['dp']
        self.kdp_method = kwargs['kdp_method']
        self.bad = kwargs['bad']
        self.thresh_sdp = kwargs['thresh_sdp']
        self.gs = kwargs['gs']
        self.name_sdp = kwargs['name_sdp']
        self.kdp_window = kwargs['kdp_window']
        flag = self.do_name_check()
        if not flag:
            return

        # Get sounding info
        self.T_flag = kwargs['use_temp']
        self.T_factor = kwargs['fhc_T_factor']
        self.get_sounding(kwargs['sounding'])
        self.winter_flag = kwargs['winter']

        # Do QC
        if kwargs['qc_flag']:
            if self.verbose:
                print('Performing QC')
            self.dz_range = kwargs['dz_range']
            self.dr_thresh = kwargs['thresh_dr']
            self.speckle = kwargs['speckle']
            self.do_qc()

        # Do FHC
        self.name_fhc = kwargs['name_fhc']
        if kwargs['fhc_flag']:
            if self.verbose:
                print('Performing FHC')
            self.fhc_weights = kwargs['fhc_weights']
            self.fhc_method = kwargs['fhc_method']
            self.band = kwargs['band']
            self.get_hid()

        # Other precip retrievals
        if kwargs['precip_flag']:
            if self.verbose:
                print('Performing precip rate calculations')
            self.get_precip_rate(ice_flag=kwargs['ice_flag'],
                                 rain_method=kwargs['rain_method'])
        if kwargs['dsd_flag']:
            if self.verbose:
                print('Performing DSD calculations')
            self.get_dsd()
        if kwargs['liquid_ice_flag']:
            if self.verbose:
                print('Performing mass calculations')
            self.get_liquid_and_frozen_mass()

    def do_radar_check(self, radar):
        """
        Checks to see if radar variable is a file or a Py-ART radar object.
        """
        if isinstance(radar, str):
            try:
                self.radar = pyart.io.read(radar)
            except:
                warnings.warn('Bad file name provided, try again')
                return False
        else:
            self.radar = radar
        # Checking for actual radar object
        try:
            junk = self.radar.latitude['data']
        except:
            warnings.warn('Need a real Py-ART radar object, try again')
            return False
        return True  # Actual radar object provided by user

    def do_name_check(self):
        """
        Simple name checking to ensure the file actually contains the
        right polarimetric variables.
        """
        wstr = ' field not in radar object, check variable names'
        if self.name_dz in self.radar.fields:
            if self.name_dr in self.radar.fields:
                if self.name_rh in self.radar.fields:
                    if self.name_ld is not None:
                        if self.name_ld not in self.radar.fields:
                            if self.verbose:
                                print('Not finding LDR field, not using')
                            self.name_ld = None
                    else:
                        if self.verbose:
                            print('Not provided LDR field, not using')
                    if self.name_kd is not None:
                        if self.name_kd not in self.radar.fields:
                            if self.verbose:
                                print('Not finding KDP field, calculating')
                            kdp_flag = self.calculate_kdp()
                        else:
                            kdp_flag = True
                    else:
                        if self.verbose:
                            print('Not provided KDP field, calculating')
                        kdp_flag = self.calculate_kdp()
                    return kdp_flag  # All required variables present?
                else:
                    warnings.warn(self.name_rh+wstr)
                    return False
            else:
                warnings.warn(self.name_dr+wstr)
                return False
        else:
            warnings.warn(self.name_dz+wstr)
            return False

    def calculate_kdp(self):
        """
        Wrapper method for calculating KDP.
        """
        wstr = 'Missing differential phase and KDP fields, failing ...'
        if self.name_dp is not None:
            if self.name_dp in self.radar.fields:
                if self.kdp_method.upper() == 'CSU':
                    kdp = self.call_csu_kdp()
                self.name_kd = 'KDP_' + self.kdp_method
                self.add_field_to_radar_object(
                    kdp, standard_name='KDP',
                    field_name=self.name_kd, units='deg km-1',
                    long_name='Specific Differential Phase')
            else:
                warnings.warn(wstr)
                return False
        else:
            warnings.warn(wstr)
            return False
        return True

    def call_csu_kdp(self):
        """
        Calls the csu_radartools.csu_kdp module to obtain KDP, FDP, and SDP.
        """
        if self.verbose:
            print('Calculating KDP via CSU method')
        dp = self.extract_unmasked_data(self.name_dp)
        dz = self.extract_unmasked_data(self.name_dz)
        kdp = np.zeros_like(dp) + self.bad
        fdp = kdp * 1.0
        sdp = kdp * 1.0
        rng = self.radar.range['data'] / RNG_MULT
        az = self.radar.azimuth['data']
        rng2d, az2d = np.meshgrid(rng, az)
        kdp, fdp, sdp = \
            csu_kdp.calc_kdp_bringi(dp=dp, dz=dz, rng=rng2d, gs=self.gs,
                                    thsd=self.thresh_sdp, bad=self.bad)
        self.name_fdp = 'FDP_'+self.kdp_method
        self.add_field_to_radar_object(
            fdp, units='deg', standard_name='Filtered Differential Phase',
            field_name=self.name_fdp,
            long_name='Filtered Differential Phase')
        self.add_field_to_radar_object(
            sdp, units='deg', standard_name='Std Dev Differential Phase',
            field_name=self.name_sdp,
            long_name='Standard Deviation of Differential Phase')
        return kdp

    def extract_unmasked_data(self, field, bad=None):
        """Extracts an unmasked field from the radar object."""
        var = self.radar.fields[field]['data']
        if hasattr(var, 'mask'):
            if bad is None:
                bad = self.bad
            var = var.filled(fill_value=bad)
        return var

    def get_sounding(self, sounding):
        """
        Ingests the sounding (either a skewt - i.e., UWYO - formatted file
        or a properly formatted dict).
        """
        if sounding is None:
            print('No sounding provided')
            self.T_flag = False
        else:
            if isinstance(sounding, str):
                try:
                    snd = SkewT.Sounding(sounding)
                    # Test for new version of skewt package
                    if hasattr(snd, 'soundingdata'):
                        self.snd_T = snd.soundingdata['temp']
                        self.snd_z = snd.soundingdata['hght']
                    else:
                        self.snd_T = snd.data['temp']
                        self.snd_z = snd.data['hght']
                except:
                    print('Sounding read fail')
                    self.T_flag = False
            else:
                try:
                    self.snd_T = sounding['T']
                    self.snd_z = sounding['z']
                except:
                    print('Sounding in wrong data format')
                    self.T_flag = False
        self.interpolate_sounding_to_radar()

    def do_qc(self):
        if self.name_sdp not in self.radar.fields:
            print('Cannot do QC, no SDP field identified')
            return
        if self.verbose:
            print('Masking insects and high SDP,', end=' ')
        dz = self.extract_unmasked_data(self.name_dz)
        dr = self.extract_unmasked_data(self.name_dr)
        sdp = self.extract_unmasked_data(self.name_sdp)
        insect_mask = csu_misc.insect_filter(
            dz, dr, dz_range=self.dz_range, dr_thresh=self.dr_thresh,
            bad=self.bad)
        sdp_mask = csu_misc.differential_phase_filter(
            sdp, thresh_sdp=self.thresh_sdp)
        new_mask = np.logical_or(insect_mask, sdp_mask)
        dz_qc = 1.0 * dz
        dz_qc[new_mask] = self.bad
        if self.verbose:
            print('Despeckling')
        mask_ds = csu_misc.despeckle(dz_qc, bad=self.bad, ngates=self.speckle)
        final_mask = np.logical_or(new_mask, mask_ds)
        setattr(self.radar.fields[self.name_dz]['data'], 'mask', final_mask)

    def get_hid(self):
        """Calculate hydrometeror ID, add to radar object."""
        dz = self.radar.fields[self.name_dz]['data']
        dr = self.radar.fields[self.name_dr]['data']
        kd = self.radar.fields[self.name_kd]['data']
        rh = self.radar.fields[self.name_rh]['data']
        if self.name_ld is not None:
            ld = self.radar.fields[self.name_ld]['data']
        else:
            ld = None
        if not self.winter_flag:
            scores = csu_fhc.csu_fhc_summer(
                dz=dz, zdr=dr, rho=rh, kdp=kd,
                ldr=ld, use_temp=self.T_flag, band=self.band,
                method=self.fhc_method, T=self.radar_T,
                verbose=self.verbose, temp_factor=self.T_factor,
                weights=self.fhc_weights)
            fh = np.argmax(scores, axis=0) + 1
            self.add_field_to_radar_object(fh, field_name=self.name_fhc)
        else:
            print('Winter HID not enabled yet, sorry!')

    def get_precip_rate(self, ice_flag=False, rain_method='hidro'):
        """Calculate rain rate, add to radar object."""
        dz = self.radar.fields[self.name_dz]['data']
        dr = self.radar.fields[self.name_dr]['data']
        kd = self.radar.fields[self.name_kd]['data']
        if not self.winter_flag:
            if rain_method == 'hidro':
                fhc = self.radar.fields[self.name_fhc]['data']
                rain, method = csu_blended_rain.csu_hidro_rain(dz=dz, zdr=dr,
                                                               kdp=kd, fhc=fhc)
            else:
                if not ice_flag:
                    rain, method = csu_blended_rain.calc_blended_rain(
                        dz=dz, zdr=dr, kdp=kd)
                else:
                    rain, method, zdp, fi = csu_blended_rain.calc_blended_rain(
                        dz=dz, zdr=dr, kdp=kd, ice_flag=ice_flag)
                    self.add_field_to_radar_object(
                        zdp, field_name='ZDP', units='dB',
                        long_name='Difference Reflectivity',
                        standard_name='Difference Reflectivity')
                    self.add_field_to_radar_object(
                        fi, field_name='FI', units='',
                        long_name='Ice Fraction', standard_name='Ice Fraction')
        else:
            print('Winter precip not enabled yet, sorry!')
            return
        self.add_field_to_radar_object(rain, field_name='rain', units='mm h-1',
                                       long_name='Rainfall Rate',
                                       standard_name='Rainfall Rate')
        self.add_field_to_radar_object(method, field_name='method', units='',
                                       long_name='Rainfall Method',
                                       standard_name='Rainfall Method')

    def get_dsd(self):
        """Calculate DSD information, add to radar object."""
        dz = self.radar.fields[self.name_dz]['data']
        dr = self.radar.fields[self.name_dr]['data']
        kd = self.radar.fields[self.name_kd]['data']
        d0, Nw, mu = csu_dsd.calc_dsd(dz=dz, zdr=dr, kdp=kd, band=self.band,
                                      method='2009')
        self.add_field_to_radar_object(d0, field_name='D0', units='mm',
                                       long_name='Median Volume Diameter',
                                       standard_name='Median Volume Diameter')
        self.add_field_to_radar_object(
            Nw, field_name='NW', units='mm-1 m-3',
            long_name='Normalized Intercept Parameter',
            standard_name='Normalized Intercept Parameter')
        self.add_field_to_radar_object(mu, field_name='MU', units=' ',
                                       long_name='Mu', standard_name='Mu')

    def get_liquid_and_frozen_mass(self):
        """Calculate liquid/ice mass, add to radar object."""
        mw, mi = csu_liquid_ice_mass.calc_liquid_ice_mass(
                         self.radar.fields[self.name_dz]['data'],
                         self.radar.fields[self.name_dr]['data'],
                         self.radar_z/1000.0, T=self.radar_T)
        self.add_field_to_radar_object(mw, field_name='MW', units='g m-3',
                                       long_name='Liquid Water Mass',
                                       standard_name='Liquid Water Mass')
        self.add_field_to_radar_object(mi, field_name='MI', units='g m-3',
                                       long_name='Ice Water Mass',
                                       standard_name='Ice Water Mass')

    def add_field_to_radar_object(self, field, field_name='FH',
                                  units='unitless', long_name='Hydrometeor ID',
                                  standard_name='Hydrometeor ID'):
        """
        Adds a newly created field to the Py-ART radar object.
        """
        masked_field = np.ma.asanyarray(field)
        fill_value = self.bad
        if hasattr(self.radar.fields[self.name_dz]['data'], 'mask'):
            setattr(masked_field, 'mask',
                    self.radar.fields[self.name_dz]['data'].mask)
            fill_value = self.radar.fields[self.name_dz]['_FillValue']
        field_dict = {'data': masked_field,
                      'units': units,
                      'long_name': long_name,
                      'standard_name': standard_name,
                      '_FillValue': fill_value}
        self.radar.add_field(field_name, field_dict, replace_existing=True)

    def interpolate_sounding_to_radar(self):
        """Takes sounding data and interpolates it to every radar gate."""
        self.radar_z = get_z_from_radar(self.radar)
        self.radar_T = None
        self.check_sounding_for_montonic()
        if self.T_flag:
            shape = np.shape(self.radar_z)
            rad_z1d = self.radar_z.ravel()
            rad_T1d = np.interp(rad_z1d, self.snd_z, self.snd_T)
            if self.verbose:
                print('Trying to get radar_T')
            self.radar_T = np.reshape(rad_T1d, shape)

    def check_sounding_for_montonic(self):
        """
        So sounding interpolation doesn't fail, force the sounding to behave
        monotonically so that z always increases. This eliminates data from
        descending balloons.
        """
        dummy_z = []
        dummy_T = []
        if hasattr(self, 'snd_T'):
            if not self.snd_T.mask[0]:  # May cause issue for some soundings
                dummy_z.append(self.snd_z[0])
                dummy_T.append(self.snd_T[0])
            for i, height in enumerate(self.snd_z):
                if i > 0:
                    if self.snd_z[i] > self.snd_z[i-1] and not\
                       self.snd_T.mask[i]:
                        dummy_z.append(self.snd_z[i])
                        dummy_T.append(self.snd_T[i])
            self.snd_z = np.array(dummy_z)
            self.snd_T = np.array(dummy_T)

################################


class HidColors(object):

    """
    Class to help with colormaps/bars when plotting
    hydrometeor ID and rainfall method data with Py-ART.

    Sample interface
    ----------------
    radar = pyart.io.read(filename)
    retrieve = dualpol.DualPolRetrieval(radar, **kwargs)
    hidcolor = dualpol.HidColors()
    display = pyart.graph.RadarDisplay(retrieve.radar)
    display.plot_ppi('FH', vmin=0, vmax=10, cmap=hidcolor.cmaphid)
    display.cbs[0] = hidcolor.adjust_fhc_colorbar_for_pyart(display.cbs[0])
    """

    def __init__(self, winter=False):
        if not winter:
            self.hid_colors = ['White', 'LightBlue', 'MediumBlue',
                               'DarkOrange', 'LightPink', 'Cyan', 'DarkGray',
                               'Lime', 'Yellow', 'Red', 'Fuchsia']
            self.cmapmeth = colors.ListedColormap(self.hid_colors[0:6])
        self.cmaphid = colors.ListedColormap(self.hid_colors)

    def adjust_fhc_colorbar_for_pyart(self, cb):
        """Mods to make a hydrometeor ID colorbar"""
        cb.set_ticks(np.arange(1.4, 10, 0.9))
        cb.ax.set_yticklabels(['Drizzle', 'Rain', 'Crystal', 'Aggregate',
                               'Wet Snow', 'Vert Ice', 'LD Graup',
                               'HD Graup', 'Hail', 'Big Drop'])
        cb.ax.set_ylabel('')
        cb.ax.tick_params(length=0)
        return cb

    def adjust_meth_colorbar_for_pyart(self, cb):
        """Mods to make a rainfall method colorbar"""
        cb.set_ticks(np.arange(1.25, 5, 0.833))
        cb.ax.set_yticklabels(['R(Kdp, Zdr)', 'R(Kdp)', 'R(Z, Zdr)', 'R(Z)',
                               'R(Zrain)'])
        cb.ax.set_ylabel('')
        cb.ax.tick_params(length=0)
        return cb

################################


def get_z_from_radar(radar):
    """Input radar object, return z from radar (km, 2D)"""
    azimuth_1D = radar.azimuth['data']
    elevation_1D = radar.elevation['data']
    srange_1D = radar.range['data']
    sr_2d, az_2d = np.meshgrid(srange_1D, azimuth_1D)
    el_2d = np.meshgrid(srange_1D, elevation_1D)[1]
    xx, yy, zz = radar_coords_to_cart(sr_2d/RNG_MULT, az_2d, el_2d)
    return zz + radar.altitude['data']


def check_kwargs(kwargs, default_kw):
    """
    Check user-provided kwargs against defaults, and if some defaults aren't
    provided by user make sure they are provided to the function regardless.
    """
    for key in default_kw:
        if key not in kwargs:
            kwargs[key] = default_kw[key]
    return kwargs

#####################################
