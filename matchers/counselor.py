import numpy as np
import pandas as pd

from .base import Matcher

from correctors import KernelSmoother
from correctors import kernels
from utilities import spherical_distance, spherical_difference, disk_to_altaz, altaz_to_disk, proj_to_disk, masked_grid


class Counselor(Matcher):
    """
    The Counselor is a Matcher that attempts to reconcile the sensor
    with the catalogue *after* the stars were paired to dots.
    """

    def __init__(self, location, time, projection_cls, catalogue, sensor_data):
        super().__init__(location, time, projection_cls)
        # a Counselor has fixed pairs: they have to be set on creation
        assert sensor_data.stars.count == catalogue.count
        self.catalogue = catalogue
        self.sensor_data = sensor_data
        self.smoother = None

        print(f"Counselor created with {self.catalogue.count} pairs:")
        print(" - " + self.catalogue.__str__())
        print(" - " + self.sensor_data.__str__())

    @property
    def count(self):
        return self.catalogue.count

    def mask_catalogue(self, mask):
        self.catalogue.set_mask(mask)
        self.sensor_data.stars.mask = mask

    def mask_sensor_data(self, mask):
        self.mask_catalogue(mask)

    @staticmethod
    def compute_distances(observed, catalogue):
        """
        Compute distance matrix for observed points projected to the sky and catalogue stars
        observed:   np.ndarray(N, 2)
        catalogue:  np.ndarray(N, 2)

        Returns
        -------
        np.ndarray(N): spherical distance between the dot and the associated star
        """
        catalogue = np.radians(catalogue)
        observed[..., 0] = np.pi / 2 - observed[..., 0]   # Convert observed altitude to co-altitude
        return spherical_distance(observed, catalogue)

    @staticmethod
    def compute_vector_errors(observed, catalogue):
        """
        Returns
        np.ndarray(N, 2): vector errors
        """
        catalogue = np.radians(catalogue)
        observed[..., 0] = np.pi / 2 - observed[..., 0]   # Convert observed altitude to co-altitude
        return spherical_difference(observed, catalogue)
        # BROKEN

    def errors(self, projection, masked):
        return self.compute_distances(
            self.sensor_data.stars.project(projection, masked=masked),
            self.catalogue.to_altaz_deg(self.location, self.time, masked=masked),
        )

    def errors_inverse(self, projection, masked):
        return self.errors(projection, masked)

    def pair(self, projection):
        self.catalogue.cull()
        self.sensor_data.stars.cull()
        return self

    def update_smoother(self, projection, *, bandwidth=0.1):
        cat = altaz_to_disk(self.catalogue.altaz(self.location, self.time, masked=True))
        obs = proj_to_disk(self.sensor_data.stars.project(projection))
        self.smoother = KernelSmoother(obs, cat - obs, kernel=kernels.nexp, bandwidth=bandwidth)

    def project_meteor(self, projection):
        xy = proj_to_disk(self.sensor_data.meteor.project(projection))
        return disk_to_altaz(xy)

    def correction_meteor_xy(self, projection):
        return self.smoother(proj_to_disk(self.sensor_data.meteor.project(projection)))

    def correct_meteor(self, projection):
        xy = proj_to_disk(self.sensor_data.meteor.project(projection))
        dxdy = self.smoother(xy)
        return disk_to_altaz(xy + dxdy)

    def grid(self, resolution=21):
        xx, yy = masked_grid(resolution)
        nodes = np.ma.stack((xx.ravel(), yy.ravel()), axis=1)
        return self.smoother(nodes).reshape(resolution, resolution, -1)

    def save(self, filename):
        self.df.to_csv(sep='\t', float_format='.6f', index=False, header=['x', 'y', 'dec', 'ra'])

    def print_meteor(self, projection):
        raw = self.project_meteor(projection)
        corr = self.correct_meteor(projection)
        df = pd.DataFrame()
        df['ev_r'] = raw.alt.degree
        df['ev'] = corr.alt.degree
        df['az_r'] = raw.az.degree
        df['az'] = corr.az.degree
        df['fno'] = 0
        df['b'] = 0
        df['bm'] = 0
        df['Lsum'] = 0
        df['mag'] = self.sensor_data.meteor.m
        df['ra'] = 0
        df['dec'] = 0
        print(df.to_xml(index=False, root_name='ua2_objpath', row_name='ua2_fdata2',
                        attr_cols=['fno', 'b', 'bm', 'Lsum', 'mag', 'az', 'ev', 'az_r', 'ev_r', 'ra', 'dec']))
