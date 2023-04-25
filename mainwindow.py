import yaml
import pytz
import datetime
import numpy as np
import dotmap

from PyQt6 import QtCore
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import QDateTime, Qt

from astropy import units as u
from astropy.coordinates import EarthLocation
import matplotlib as mpl

from matchers import Matchmaker, Counselor
from projections import BorovickaProjection
from plotting import MainWindowPlots

import colour as c
from amos import AMOS, Station
from logger import setupLog

mpl.use('Qt5Agg')

VERSION = "0.6.2"
DATE = "2023-04-25"

log = setupLog(__name__)


class MainWindow(MainWindowPlots):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.populateStations()
        self.updateProjection()

        self.connectSignalSlots()
        self.updateLocation()
        self.updateTime()
        self.matcher = Matchmaker(self.location, self.time)
        self.matcher.load_catalogue('catalogues/HYG30.tsv')
        self._loadSighting('data/M20121022_234351_AGO__00002.yaml')
        self._importProjectionConstants('calibrations/AGO2.yaml')
        self.onParametersChanged()

    def connectSignalSlots(self):
        self.ac_load_sighting.triggered.connect(self.loadSighting)
        self.ac_load_catalogue.triggered.connect(self.loadCatalogue)
        self.ac_load_constants.triggered.connect(self.importProjectionConstants)
        self.ac_save_constants.triggered.connect(self.exportProjectionConstants)
        self.ac_export_meteor.triggered.connect(self.exportCorrectedMeteor)
        self.ac_mask_unmatched.triggered.connect(self.maskSensor)
        self.ac_create_pairing.triggered.connect(self.pair)
        self.ac_about.triggered.connect(self.displayAbout)

        for widget, param in self.param_widgets:
            widget.valueChanged.connect(self.onParametersChanged)

        self.dt_time.dateTimeChanged.connect(self.updateTime)
        self.dt_time.dateTimeChanged.connect(self.onTimeChanged)

        self.dsb_lat.valueChanged.connect(self.onLocationChanged)
        self.dsb_lon.valueChanged.connect(self.onLocationChanged)

        self.pb_optimize.clicked.connect(self.minimize)
        self.pb_pair.clicked.connect(self.pair)
        self.pb_export.clicked.connect(self.exportProjectionConstants)
        self.pb_import.clicked.connect(self.importProjectionConstants)

        self.pb_mask_unidentified.clicked.connect(self.maskSensor)
        self.pb_mask_distant.clicked.connect(self.maskCatalogueDistant)
        self.pb_mask_faint.clicked.connect(self.maskCatalogueFaint)
        self.pb_reset.clicked.connect(self.resetValid)
        self.dsb_error_limit.valueChanged.connect(self.onErrorLimitChanged)

        self.hs_bandwidth.actionTriggered.connect(self.onBandwidthSettingChanged)
        self.hs_bandwidth.sliderMoved.connect(self.onBandwidthSettingChanged)
        self.hs_bandwidth.actionTriggered.connect(self.onBandwidthChanged)
        self.hs_bandwidth.sliderReleased.connect(self.onBandwidthChanged)
        self.sb_arrow_scale.valueChanged.connect(self.onArrowScaleChanged)
        self.sb_resolution.valueChanged.connect(self.onResolutionChanged)

        self.cb_show_errors.clicked.connect(self.plotPositionCorrectionErrors)
        self.cb_show_grid.clicked.connect(self.plotPositionCorrectionGrid)
        self.cb_interpolation.currentIndexChanged.connect(self.plotMagnitudeCorrectionGrid)

        self.tw_charts.currentChanged.connect(self.updatePlots)

    def populateStations(self):
        for name, station in AMOS.stations.items():
            self.cb_stations.addItem(station.name)

        self.cb_stations.currentIndexChanged.connect(self.selectStation)

    def selectStation(self, index):
        if index == 0:
            station = Station("custom", self.dsb_lat.value(), self.dsb_lon.value(), self.dsb_alt.value())
        else:
            station = list(AMOS.stations.values())[index - 1]

        self.dsb_lat.setValue(station.latitude)
        self.dsb_lon.setValue(station.longitude)
        self.dsb_alt.setValue(station.altitude)

        self.updateMatcher()
        self.onLocationTimeChanged()

    def onTimeChanged(self):
        self.updateTime()
        self.onLocationTimeChanged()

    def onLocationChanged(self):
        self.updateLocation()
        self.onLocationTimeChanged()

    def setLocation(self, lat, lon, alt):
        self.dsb_lat.setValue(lat)
        self.dsb_lon.setValue(lon)
        self.dsb_alt.setValue(alt)

    def updateLocation(self):
        self.location = EarthLocation(self.dsb_lon.value() * u.deg,
                                      self.dsb_lat.value() * u.deg,
                                      self.dsb_alt.value() * u.m)

    def setTime(self, time):
        time = QDateTime(time.date(), time.time(), Qt.TimeSpec.UTC)
        self.dt_time.setDateTime(time)

    def updateTime(self):
        self.time = self.dt_time.dateTime().toPyDateTime()

    def updateMatcher(self):
        self.matcher.update(self.location, self.time)
        self.matcher.update_position_smoother(self.projection)

    def updateProjection(self):
        self.projection = BorovickaProjection(*self.getConstantsTuple())

    def onParametersChanged(self):
        log.info("Parameters changed")
        self.updateProjection()

        self.positionSkyPlot.invalidate_dots()
        self.positionSkyPlot.invalidate_meteor()
        self.magnitudeSkyPlot.invalidate_dots()
        self.magnitudeSkyPlot.invalidate_meteor()
        self.positionErrorPlot.invalidate()
        self.magnitudeErrorPlot.invalidate()
        self.positionCorrectionPlot.invalidate()
        self.magnitudeCorrectionPlot.invalidate()
        self.matcher.update_position_smoother(self.projection, bandwidth=self.bandwidth())

        self.computePositionErrors()
        self.computeMagnitudeErrors()
        self.updatePlots()

    def onLocationTimeChanged(self):
        self.updateMatcher()
        self.positionSkyPlot.invalidate_stars()
        self.magnitudeSkyPlot.invalidate_stars()
        self.positionErrorPlot.invalidate()
        self.magnitudeErrorPlot.invalidate()

        bandwidth = self.bandwidth()
        self.matcher.update_position_smoother(self.projection, bandwidth=bandwidth)
        self.matcher.update_magnitude_smoother(self.projection, self.calibration, bandwidth=bandwidth)
        self.positionCorrectionPlot.invalidate()
        self.magnitudeCorrectionPlot.invalidate()

        self.computePositionErrors()
        self.computeMagnitudeErrors()
        self.updatePlots()

    def onErrorLimitChanged(self):
        self.positionSkyPlot.invalidate_dots()
        self.positionErrorPlot.invalidate()
        self.positionCorrectionPlot.invalidate_dots()
        self.updatePlots()

    def onBandwidthSettingChanged(self):
        bandwidth = self.bandwidth()
        self.lb_bandwidth.setText(f"{bandwidth:.03f}")

    def onBandwidthChanged(self, action=0):
        if action == 7:
            return

        bandwidth = self.bandwidth()
        self.matcher.update_position_smoother(self.projection, bandwidth=bandwidth)
        self.matcher.update_magnitude_smoother(self.projection, self.calibration, bandwidth=bandwidth)
        self.positionCorrectionPlot.invalidate_grid()
        self.positionCorrectionPlot.invalidate_meteor()
        self.magnitudeCorrectionPlot.invalidate_grid()
        self.magnitudeCorrectionPlot.invalidate_meteor()
        self.updatePlots()

    def onArrowScaleChanged(self):
        self.positionCorrectionPlot.invalidate_dots()
        self.positionCorrectionPlot.invalidate_meteor()
        self.updatePlots()

    def onResolutionChanged(self):
        self.positionCorrectionPlot.invalidate_grid()
        self.magnitudeCorrectionPlot.invalidate_grid()
        self.updatePlots()

    def bandwidth(self):
        return 10**(-self.hs_bandwidth.value() / 100)

    def computePositionErrors(self):
        self.position_errors = self.matcher.position_errors(self.projection, masked=True)

    def computeMagnitudeErrors(self):
        self.magnitude_errors = self.matcher.magnitude_errors(self.projection, self.calibration, masked=True)

    def loadCatalogue(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load catalogue file", "catalogues",
                                                  "Tab-separated values (*.tsv)")
        if filename == '':
            log.warn("No file provided, loading aborted")
        else:
            self.matcher.load_catalogue(filename)
            self.onParametersChanged()

    def exportProjectionConstants(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export constants to file", "calibrations",
                                                  "YAML files (*.yaml)")
        if filename is not None and filename != '':
            self._exportProjectionConstants(filename)

    def _exportProjectionConstants(self, filename):
        try:
            with open(filename, 'w+') as file:
                yaml.dump(dict(
                    proj='Borovicka',
                    params=dict(
                        x0=self.dsb_x0.value(),
                        y0=self.dsb_y0.value(),
                        a0=self.dsb_a0.value(),
                        A=self.dsb_A.value(),
                        F=self.dsb_F.value(),
                        V=self.dsb_V.value(),
                        S=self.dsb_S.value(),
                        D=self.dsb_D.value(),
                        P=self.dsb_P.value(),
                        Q=self.dsb_Q.value(),
                        eps=self.dsb_eps.value(),
                        E=self.dsb_E.value(),
                    )
                ), file)
        except FileNotFoundError as exc:
            log.error(f"Could not export constants: {exc}")

    def loadSighting(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Kvant YAML file", "data",
                                                  "YAML files (*.yml *.yaml)")
        if filename == '':
            log.warn("No file provided, loading aborted")
        else:
            self._loadSighting(filename)

        self.cb_stations.setCurrentIndex(0)
        self.onLocationTimeChanged()
        self.onParametersChanged()
        self.sensorPlot.invalidate()
        self.updatePlots()

    def _loadSighting(self, file):
        data = dotmap.DotMap(yaml.safe_load(open(file, 'r')))
        self.setLocation(data.Latitude, data.Longitude, data.Altitude)
        self.updateLocation()
        self.setTime(pytz.UTC.localize(datetime.datetime.strptime(data.EventStartTime, "%Y-%m-%d %H:%M:%S.%f")))
        self.updateTime()
        self.sensorPlot.invalidate()

        self.matcher.sensor_data.load(data)

    def importProjectionConstants(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import constants from file", "calibrations",
                                                  "YAML files (*.yml *.yaml)")
        self._importProjectionConstants(filename)
        self.onParametersChanged()

    def _importProjectionConstants(self, filename):
        try:
            with open(filename, 'r') as file:
                try:
                    data = dotmap.DotMap(yaml.safe_load(file))
                    self.blockParameterSignals(True)
                    for widget, param in self.param_widgets:
                        widget.setValue(data.params[param])
                    self.blockParameterSignals(False)

                    self.updateProjection()
                except yaml.YAMLError as exc:
                    log.error(f"Could not parse file {filename} as YAML: {exc}")
        except FileNotFoundError as exc:
            log.error(f"Could not import constants: {exc}")

    def blockParameterSignals(self, block):
        for widget, param in self.param_widgets:
            widget.blockSignals(block)

    def getConstantsTuple(self):
        return (
            self.dsb_x0.value(),
            self.dsb_y0.value(),
            np.radians(self.dsb_a0.value()),
            self.dsb_A.value(),
            np.radians(self.dsb_F.value()),
            self.dsb_V.value(),
            self.dsb_S.value(),
            self.dsb_D.value(),
            self.dsb_P.value(),
            self.dsb_Q.value(),
            np.radians(self.dsb_eps.value()),
            np.radians(self.dsb_E.value()),
        )

    def minimize(self):
        self.w_input.setEnabled(False)
        self.w_input.repaint()

        result = self.matcher.minimize(
            #    location=self.location,
            #    time=self.time,
            x0=self.getConstantsTuple(),
            maxiter=self.sb_maxiter.value()
        )

        x0, y0, a0, A, F, V, S, D, P, Q, e, E = tuple(result.x)
        self.blockParameterSignals(True)
        self.dsb_x0.setValue(x0)
        self.dsb_y0.setValue(y0)
        self.dsb_a0.setValue(np.degrees(a0))
        self.dsb_A.setValue(A)
        self.dsb_F.setValue(np.degrees(F))
        self.dsb_V.setValue(V)
        self.dsb_S.setValue(S)
        self.dsb_D.setValue(D)
        self.dsb_P.setValue(P)
        self.dsb_Q.setValue(Q)
        self.dsb_eps.setValue(np.degrees(e))
        self.dsb_E.setValue(np.degrees(E))
        self.blockParameterSignals(False)

        self.w_input.setEnabled(True)
        self.w_input.repaint()
        self.onParametersChanged()

    def maskSensor(self):
        errors = self.matcher.position_errors(self.projection, masked=False)
        self.matcher.mask_sensor_data(errors > np.radians(self.dsb_error_limit.value()))
        log.info(f"Culled the dots to {c.param(self.dsb_error_limit.value())}°: "
              f"{c.num(self.matcher.sensor_data.stars.count_valid)} are valid")
        self.onParametersChanged()
        self.showCounts()

    def maskCatalogueDistant(self):
        errors = self.matcher.position_errors_inverse(self.projection, masked=False)
        self.matcher.mask_catalogue(errors > np.radians(self.dsb_distance_limit.value()))
        log.info(f"Culled the catalogue to {self.dsb_distance_limit.value()}°: "
              f"{self.matcher.catalogue.count_valid} stars used")
        self.positionSkyPlot.invalidate_stars()

        self.computePositionErrors()
        self.computeMagnitudeErrors()
        self.updatePlots()
        self.showCounts()

    def maskCatalogueFaint(self):
        self.matcher.mask_catalogue(self.matcher.catalogue.vmag(False) > self.dsb_magnitude_limit.value())
        log.info(f"Culled the catalogue to magnitude {self.dsb_magnitude_limit.value()}m: "
              f"{self.matcher.catalogue.count_valid} stars used")
        self.positionSkyPlot.invalidate_stars()

        self.computePositionErrors()
        self.computeMagnitudeErrors()
        self.updatePlots()
        self.showCounts()

    def resetValid(self):
        self.matcher.reset_mask()
        self.onParametersChanged()
        self.showCounts()

    @QtCore.pyqtSlot()
    def showCounts(self) -> None:
        if isinstance(self.matcher, Counselor):
            self.lb_mode.setText("paired")
            self.tab_correction_magnitudes_enabled.setEnabled(True)
        else:
            self.lb_mode.setText("unpaired")
            self.tab_correction_magnitudes_enabled.setEnabled(False)

        self.lb_catalogue_all.setText(f'{self.matcher.catalogue.count}')
        self.lb_catalogue_near.setText(f'{self.matcher.catalogue.count_valid}')
        self.lb_objects_all.setText(f'{self.matcher.sensor_data.stars.count}')
        self.lb_objects_near.setText(f'{self.matcher.sensor_data.stars.count_valid}')

    def showErrors(self) -> None:
        avg_error = self.matcher.avg_error(self.position_errors)
        max_error = self.matcher.max_error(self.position_errors)
        self.lb_avg_error.setText(f'{np.degrees(avg_error):.6f}°')
        self.lb_max_error.setText(f'{np.degrees(max_error):.6f}°')
        self.lb_total_stars.setText(f'{self.matcher.catalogue.count}')
        outside_limit = self.position_errors[self.position_errors > np.radians(self.dsb_error_limit.value())].size
        self.lb_outside_limit.setText(f'{outside_limit}')

    def exportCorrectedMeteor(self):
        if not self.paired:
            log.warn("Cannot export a meteor before pairing dots to the catalogue")
            return None

        filename, _ = QFileDialog.getSaveFileName(self, "Export corrected meteor to file", "output/",
                                                  "XML files (*.xml)")
        if filename is not None and filename != '':
            with open(filename, 'w') as file:
                file.write(f"""<?xml version="1.0" encoding="UTF-8" ?>
<ufoanalyzer_record version ="200"
    clip_name="{self.matcher.sensor_data.id}"
    o="1"
    y="{self.time.strftime("%Y")}"
    mo="{self.time.strftime("%m")}"
    d="{self.time.strftime("%d")}"
    h="{self.time.strftime("%H")}"
    m="{self.time.strftime("%M")}"
    s="{self.time.strftime('%S.%f')}"
    tz="0" tme="0" lid="{self.matcher.sensor_data.station}" sid="kvant"
    lng="{self.dsb_lon.value()}" lat="{self.dsb_lat.value()}" alt="{self.dsb_alt.value()}"
    cx="{self.matcher.sensor_data.rect.xmax}" cy="{self.matcher.sensor_data.rect.ymax}" fps="15" interlaced="0" bbf="0"
    frames="{self.matcher.sensor_data.meteor.count}" head="0" tail="0" drop="-1"
    dlev="0" dsize="0" sipos="0" sisize="0"
    trig="0" observer="{self.matcher.sensor_data.station}" cam="" lens=""
    cap="" u2="0" ua="0" memo=""
    az="0" ev="0" rot="0" vx="0"
    yx="0" dx="0" dy="0" k4="0"
    k3="0" k2="0" atc="0" BVF="0"
    maxLev="0" maxMag="0" minLev="0" mimMag="0"
    dl="0" leap="0" pixs="0" rstar="0.0283990702993807"
    ddega="0.03276" ddegm="0" errm="0" Lmrgn="0"
    Rmrgn="0" Dmrgn="0" Umrgn="0">
    <ua2_objects>
        <ua2_object
            fs="20" fe="64" fN="45" sN="45"
            sec="3" av="0" pix="0" bmax="0"
            bN="0" Lmax="0" mag="0" cdeg="0"
            cdegmax="0" io="0" raP="0" dcP="0"
            av1="0" x1="0" y1="0" x2="0"
            y2="0" az1="0" ev1="0" az2="0"
            ev2="0" azm="0" evm="0" ra1="0"
            dc1="0" ra2="0" dc2="0" ram="0"
            dcm="0" class="spo" m="0" dr="0"
            dv="0" Vo="0" lng1="0" lat1="0"
            h1="0" dist1="0" gd1="0" azL1="0"
            evL1="0" lng2="0" lat2="0" h2="0"
            dist2="0" gd2="0" len="0" GV="0"
            rao="0" dco="0" Voo="0" rat="0"
            dct="0" memo=""
            CodeRed="G"
            ACOM="324"
            sigma="0.03276"
            sigma.azi="0.0283990702993807"
            sigma.zen="0.0354915982362712"
            A0="{self.projection.axis_shifter.a0}"
            X0="{self.projection.axis_shifter.x0}"
            Y0="{self.projection.axis_shifter.y0}"
            V="{self.projection.radial_transform.linear}"
            S="{self.projection.radial_transform.lin_coef}"
            D="{self.projection.radial_transform.lin_exp}"
            EPS="{self.projection.zenith_shifter.epsilon}"
            E="{self.projection.zenith_shifter.E}"
            A="{self.projection.axis_shifter.A}"
            F0="{self.projection.axis_shifter.F}"
            P="{self.projection.radial_transform.quad_coef}"
            Q="{self.projection.radial_transform.quad_exp}"
            C="1"
            CH1="690"
            CH2="0.00494625"
            CH3="535"
            CH4="0.004992"
            magA="7.34131408453742"
            magB="1.50852603934261"
            magR2="0.548439901974541"
            magS="0.399746731883133"
            usingPrecession="True">
""")
                file.write(self.matcher.print_meteor(self.projection, self.calibration))
                file.write("""
        </ua2_object>
    </ua2_objects>
</ufoanalyzer_record>""")

    @property
    def grid_resolution(self):
        return self.sb_resolution.value()

    def pair(self):
        self.matcher = self.matcher.pair(self.projection)
        self.matcher.update_position_smoother(self.projection, bandwidth=self.bandwidth())
        self.matcher.update_magnitude_smoother(self.projection, self.calibration, bandwidth=self.bandwidth())

        self.positionSkyPlot.invalidate_dots()
        self.positionSkyPlot.invalidate_stars()
        self.magnitudeSkyPlot.invalidate_dots()
        self.magnitudeSkyPlot.invalidate_stars()
        self.positionErrorPlot.invalidate()
        self.magnitudeErrorPlot.invalidate()
        self.positionCorrectionPlot.invalidate()
        self.magnitudeCorrectionPlot.invalidate()
        self.showCounts()
        self.updatePlots()

    def displayAbout(self):
        msg = QMessageBox(parent=self, text="VASCO Virtual All-Sky CorrectOr plate")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("About")
        msg.setModal(True)
        msg.setInformativeText(f"Version {VERSION}, built on {DATE}")
        msg.show()
        msg.move((self.width() - msg.width()) // 2, (self.height() - msg.height()) // 2)
        return msg.exec()
