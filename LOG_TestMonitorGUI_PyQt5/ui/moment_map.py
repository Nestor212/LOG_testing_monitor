import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

class MomentMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Moment Map")
        self.resize(1000, 500)

        layout = QVBoxLayout(self)
        self.fig = Figure(figsize=(10, 4))
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self.info_label = QLabel("Torque and force info here")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.info_label.setFont(font)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setMinimumHeight(30)
        layout.addWidget(self.info_label)

        gs = gridspec.GridSpec(2, 2, figure=self.fig, height_ratios=[0.05, 1])
        self.axs = [
            self.fig.add_subplot(gs[1, 0]),
            self.fig.add_subplot(gs[1, 1])
        ]
        self.cbar_axes = [
            self.fig.add_subplot(gs[0, 0]),
            self.fig.add_subplot(gs[0, 1])
        ]

        self.X, self.Y = np.meshgrid(np.linspace(0, 21, 30), np.linspace(0, 12, 20))
        self.Tau_x = np.zeros_like(self.X)
        self.Tau_y = np.zeros_like(self.X)
        self.Tau_z = np.zeros_like(self.X)
        self.U = np.zeros_like(self.X)
        self.V = np.zeros_like(self.Y)

        for ax in self.axs:
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
            ax.set_aspect("equal")

        # Initial dummy contours
        self.im1 = self.axs[0].contourf(self.X, self.Y, np.zeros_like(self.X),
                                        levels=np.linspace(0, 10, 20), cmap='coolwarm')
        self.im2 = self.axs[1].contourf(self.X, self.Y, np.zeros_like(self.X),
                                        levels=np.linspace(-10, 10, 20), cmap='coolwarm')

        self.cbar1 = self.fig.colorbar(self.im1, cax=self.cbar_axes[0], orientation='horizontal')
        self.cbar2 = self.fig.colorbar(self.im2, cax=self.cbar_axes[1], orientation='horizontal')
        self._style_colorbars()
        self.canvas.draw()

    def _style_colorbars(self):
        self.cbar1.ax.tick_params(labelsize=8)
        self.cbar2.ax.tick_params(labelsize=8)
        self.cbar1.ax.locator_params(nbins=5)
        self.cbar2.ax.locator_params(nbins=5)

    def update_forces(self, fx_vals, fy_vals, fz_vals):
        pos_fx = np.array([[10, 6]])
        pos_fy = np.array([[18, 3.5], [3, 3.5]])
        pos_fz = np.array([[20.25, 11.25], [10.5, 0.75], [0.75, 11.25]])

        self.Tau_x.fill(0)
        self.Tau_y.fill(0)
        self.Tau_z.fill(0)
        self.U.fill(0)
        self.V.fill(0)

        fx_vals = np.nan_to_num(fx_vals)
        fy_vals = np.nan_to_num(fy_vals)
        fz_vals = np.nan_to_num(fz_vals)

        for (px, py), fz in zip(pos_fz, fz_vals):
            dx = self.Y - py
            dy = self.X - px
            self.Tau_x += dx * fz
            self.Tau_y -= dy * fz

        for (px, py), fx in zip(pos_fx, fx_vals):
            self.Tau_z += -(self.Y - py) * fx
            self.U += fx

        for (px, py), fy in zip(pos_fy, fy_vals):
            self.Tau_z += (self.X - px) * fy
            self.V += fy

        tau_mag = np.sqrt(self.Tau_x ** 2 + self.Tau_y ** 2)

        # Clear axes
        self.axs[0].cla()
        self.axs[1].cla()

        max_tau_mag = np.nanmax(tau_mag)
        max_tau_z = np.nanmax(np.abs(self.Tau_z))

        if max_tau_mag == 0:
            max_tau_mag = 1e-6
        if max_tau_z == 0:
            max_tau_z = 1e-6

        levels_xy = np.linspace(0, max_tau_mag, 20)
        levels_z = np.linspace(-max_tau_z, max_tau_z, 20)

        self.im1 = self.axs[0].contourf(self.X, self.Y, tau_mag, levels=levels_xy, cmap='coolwarm')
        self.im2 = self.axs[1].contourf(self.X, self.Y, self.Tau_z, levels=levels_z, cmap='coolwarm')

        self.axs[0].quiver(self.X, self.Y, self.Tau_y, self.Tau_x, scale=100, color='black', alpha=0.1)
        self.axs[1].quiver(self.X, self.Y, self.U, self.V, scale=50, color='k', alpha=0.1)

        self.axs[0].set_title("Moment X/Y Magnitude + Direction")
        self.axs[1].set_title("Moment Z + Lateral Forces")
        for ax in self.axs:
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
            ax.set_aspect("equal")

        # --- Clean colorbar recreation ---
        self.cbar_axes[0].cla()
        self.cbar_axes[1].cla()
        self.cbar1 = self.fig.colorbar(self.im1, cax=self.cbar_axes[0], orientation='horizontal')
        self.cbar2 = self.fig.colorbar(self.im2, cax=self.cbar_axes[1], orientation='horizontal')
        self._style_colorbars()

        self.canvas.draw_idle()

        # Net forces + moments
        Fz_total = sum(fz_vals)
        Fx_total = sum(fx_vals)
        Fy_total = sum(fy_vals)

        tau_x_total = sum((y - 6) * fz for (x, y), fz in zip(pos_fz, fz_vals))
        tau_y_total = -sum((x - 10.5) * fz for (x, y), fz in zip(pos_fz, fz_vals))
        tau_z_total = sum(x * fy - y * fx for (x, y), fx, fy in zip([*pos_fx, *pos_fy], fx_vals + [0], [0] + fy_vals))

        info = (
            f"Fx: {Fx_total:.2f}  Fy: {Fy_total:.2f}  Fz: {Fz_total:.2f} | "
            f"τx: {tau_x_total:.2f}  τy: {tau_y_total:.2f}  τz: {tau_z_total:.2f}"
        )
        self.info_label.setText(info)
