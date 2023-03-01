import numpy as np
import matplotlib as mpl

from plots.base import BasePlot


class BaseSkyPlot(BasePlot):
    @staticmethod
    def to_chart(positions):
        return np.stack(
            (positions[:, 1], np.degrees(positions[:, 0])),
            axis=1,
        )

    def __init__(self, widget, **kwargs):
        self.cmap_stars = mpl.cm.get_cmap('autumn_r')
        self.cmap_meteors = mpl.cm.get_cmap('Blues_r')
        self.scatter_stars = None
        self.scatter_dots = None
        self.scatter_meteor = None
        self.valid_stars = False
        self.valid_dots = False
        self.valid_meteor = False
        super().__init__(widget, **kwargs)

    def add_axes(self):
        self.axis = self.figure.add_subplot(projection='polar')
        self.axis.set_xlim([0, 2 * np.pi])
        self.axis.set_ylim([0, 90])
        self.axis.set_rlabel_position(0)
        self.axis.set_rticks([15, 30, 45, 60, 75])
        self.axis.yaxis.set_major_formatter('{x}°')
        self.axis.grid(color='white', alpha=0.3)
        self.axis.set_theta_offset(3 * np.pi / 2)

        self.scatter_stars = self.axis.scatter([], [], s=[], c='white', marker='o')
        self.scatter_dots = self.axis.scatter([], [], s=[], c='red', marker='x')
        self.scatter_meteor = self.axis.scatter([], [], s=[], c='cyan', marker='o')

    def invalidate_stars(self):
        self.valid_stars = False

    def invalidate_dots(self):
        self.valid_dots = False

    def invalidate_meteor(self):
        self.valid_meteor = False

    def update_stars(self, positions, magnitudes):
        sizes = 0.2 * np.exp(-0.833 * (magnitudes - 5))
        self.scatter_stars.set_offsets(positions)
        self.scatter_stars.set_sizes(sizes)

        self.valid_stars = True
        self.draw()

    def update_dots(self, positions, magnitudes, errors, *, limit=1):
        self.scatter_dots.set_offsets(self.to_chart(positions))

        norm = mpl.colors.Normalize(vmin=0, vmax=limit)
        self.scatter_dots.set_facecolors(self.cmap_stars(norm(errors)))
        self.scatter_dots.set_sizes(0.03 * magnitudes)

        self.valid_dots = True
        self.draw()

    def update_meteor(self, positions, magnitudes):
        self.scatter_meteor.set_offsets(self.to_chart(positions))

        norm = mpl.colors.Normalize(vmin=0, vmax=None)
        self.scatter_meteor.set_facecolors(self.cmap_meteors(norm(magnitudes)))
        self.scatter_meteor.set_sizes(0.0005 * magnitudes)

        self.valid_meteor = True
        self.draw()