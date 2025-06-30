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

        self.levels_xy = np.linspace(0, 10, 20)
        self.levels_z = np.linspace(-10, 10, 20)

        self.im1 = self.axs[0].contourf(self.X, self.Y, np.zeros_like(self.X), levels=self.levels_xy, cmap='coolwarm')
        self.im2 = self.axs[1].contourf(self.X, self.Y, np.zeros_like(self.X), levels=self.levels_z, cmap='coolwarm')

        self.cbar1 = self.fig.colorbar(self.im1, cax=self.cbar_axes[0], orientation='horizontal')
        self.cbar2 = self.fig.colorbar(self.im2, cax=self.cbar_axes[1], orientation='horizontal')
        self._style_colorbars()

        self.quiv1 = self.axs[0].quiver(self.X, self.Y, np.zeros_like(self.X), np.zeros_like(self.Y),
                                        scale=100, color='black', alpha=0.1)
        self.quiv2 = self.axs[1].quiver(self.X, self.Y, np.zeros_like(self.X), np.zeros_like(self.Y),
                                        scale=50, color='k', alpha=0.1)

        self._prev_max_tau_mag = 10
        self._prev_max_tau_z = 10
        self.counter1 = 0
        self.counter2 = 0

        self._tau_mag_history = []
        self._tau_z_history = []
        self._noise_buffer_size = 100  # Number of recent samples to track
        self._update_counter = 0
        self._noise_report_interval = 50  # How often to print stats


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
        max_tau_mag = max(np.nanmax(tau_mag), 1e-6)
        max_tau_z = max(np.nanmax(np.abs(self.Tau_z)), 1e-6)

        levels_xy_changed = False
        levels_z_changed = False

        delta_buffer = 1.2
        grow_thresh_xy = 1.05
        shrink_thresh = 1.3
        grow_thresh_z = 1.1
        shrink_thresh_z = 1.5
        min_delta_frac = 0.1  # 10% minimum change for levels

        # τx/y logic
        if max_tau_mag < 10:
            if self._prev_max_tau_mag != 10:
                print("[MomentMap] Max τx/y magnitude is too low, resetting to 10")
                self._prev_max_tau_mag = 10
                self.levels_xy = np.linspace(0, self._prev_max_tau_mag, 20)
                levels_xy_changed = True
                self._xy_shrink_count = 0
                self._xy_grow_count = 0
        else:
            if max_tau_mag > self._prev_max_tau_mag:# * grow_thresh_xy:
                self._xy_grow_count = getattr(self, '_xy_grow_count', 0) + 1
                if self._xy_grow_count >= 3:
                    new_max = max_tau_mag * delta_buffer
                    if abs(new_max - self._prev_max_tau_mag) / self._prev_max_tau_mag > min_delta_frac:
                        print(f"[MomentMap] Expanding levels for XY: {self._prev_max_tau_mag:.2f} -> {new_max:.2f}")
                        self._prev_max_tau_mag = new_max
                        self.levels_xy = np.linspace(0, self._prev_max_tau_mag, 20)
                        levels_xy_changed = True
                    self._xy_grow_count = 0
            else:
                self._xy_grow_count = 0

            if max_tau_mag < self._prev_max_tau_mag / shrink_thresh:
                self._xy_shrink_count = getattr(self, '_xy_shrink_count', 0) + 1
                if self._xy_shrink_count >= 3:
                    new_max = max_tau_mag * delta_buffer
                    if abs(new_max - self._prev_max_tau_mag) / self._prev_max_tau_mag > min_delta_frac:
                        print(f"[MomentMap] Shrinking levels for XY: {self._prev_max_tau_mag:.2f} -> {new_max:.2f}")
                        self._prev_max_tau_mag = new_max
                        self.levels_xy = np.linspace(0, self._prev_max_tau_mag, 20)
                        levels_xy_changed = True
                    self._xy_shrink_count = 0
            else:
                self._xy_shrink_count = 0

        # τz logic
        if max_tau_z < 10:
            if self._prev_max_tau_z != 10:
                print("[MomentMap] Max τz is too low, resetting to 10")
                self._prev_max_tau_z = 10
                self.levels_z = np.linspace(-self._prev_max_tau_z, self._prev_max_tau_z, 20)
                levels_z_changed = True
                self._z_shrink_count = 0
                self._z_grow_count = 0
        else:
            if max_tau_z > self._prev_max_tau_z:# * grow_thresh_z:
                self._z_grow_count = getattr(self, '_z_grow_count', 0) + 1
                if self._z_grow_count >= 3:
                    new_max = max_tau_z * delta_buffer
                    if abs(new_max - self._prev_max_tau_z) / self._prev_max_tau_z > min_delta_frac:
                        print(f"[MomentMap] Expanding levels for Z: {self._prev_max_tau_z:.2f} -> {new_max:.2f}")
                        self._prev_max_tau_z = new_max
                        self.levels_z = np.linspace(-self._prev_max_tau_z, self._prev_max_tau_z, 20)
                        levels_z_changed = True
                    self._z_grow_count = 0
            else:
                self._z_grow_count = 0

            if max_tau_z < self._prev_max_tau_z / shrink_thresh:
                self._z_shrink_count = getattr(self, '_z_shrink_count', 0) + 1
                if self._z_shrink_count >= 3:
                    new_max = max_tau_z * delta_buffer
                    if abs(new_max - self._prev_max_tau_z) / self._prev_max_tau_z > min_delta_frac:
                        print(f"[MomentMap] Shrinking levels for Z: {self._prev_max_tau_z:.2f} -> {new_max:.2f}")
                        self._prev_max_tau_z = new_max
                        self.levels_z = np.linspace(-self._prev_max_tau_z, self._prev_max_tau_z, 20)
                        levels_z_changed = True
                    self._z_shrink_count = 0
            else:
                self._z_shrink_count = 0

        self.im1.remove()
        self.im2.remove()

        self.im1 = self.axs[0].contourf(self.X, self.Y, tau_mag, levels=self.levels_xy, cmap='coolwarm')
        self.im2 = self.axs[1].contourf(self.X, self.Y, self.Tau_z, levels=self.levels_z, cmap='coolwarm')

        if levels_xy_changed:
            self.counter1 += 1
            print(f"[MomentMap] Levels for XY changed {self.counter1} times, updating.")
            self.cbar_axes[0].cla()
            self.cbar1 = self.fig.colorbar(self.im1, cax=self.cbar_axes[0], orientation='horizontal')
            self._style_colorbars()
        else:
            self.cbar1.update_normal(self.im1)

        if levels_z_changed:
            self.counter2 += 1
            print(f"[MomentMap] Levels for Z changed {self.counter2} times, updating.")
            self.cbar_axes[1].cla()
            self.cbar2 = self.fig.colorbar(self.im2, cax=self.cbar_axes[1], orientation='horizontal')
            self._style_colorbars()
        else:
            self.cbar2.update_normal(self.im2)

        self.quiv1.remove()
        self.quiv2.remove()
        self.quiv1 = self.axs[0].quiver(self.X, self.Y, self.Tau_y, self.Tau_x, scale=100, color='black', alpha=0.1)
        self.quiv2 = self.axs[1].quiver(self.X, self.Y, self.U, self.V, scale=50, color='k', alpha=0.1)

        self.axs[0].set_title("Moment X/Y Magnitude + Direction")
        self.axs[1].set_title("Moment Z + Lateral Forces")

        self.canvas.draw_idle()

        Fz_total = sum(fz_vals)
        Fx_total = sum(fx_vals)
        Fy_total = sum(fy_vals)

        tau_x_total = sum((y - 6) * fz for (x, y), fz in zip(pos_fz, fz_vals))
        tau_y_total = -sum((x - 10.5) * fz for (x, y), fz in zip(pos_fz, fz_vals))
        tau_z_total = sum(
            x * fy - y * fx
            for (x, y), fx, fy in zip([*pos_fx, *pos_fy], fx_vals + [0], [0] + fy_vals)
        )

        info = (
            f"Fx: {Fx_total:.2f}  Fy: {Fy_total:.2f}  Fz: {Fz_total:.2f} | "
            f"τx: {tau_x_total:.2f}  τy: {tau_y_total:.2f}  τz: {tau_z_total:.2f}"
        )
        self.info_label.setText(info)

        # Collect data
        self._tau_mag_history.append(max_tau_mag)
        self._tau_z_history.append(max_tau_z)

        # Trim to buffer size
        if len(self._tau_mag_history) > self._noise_buffer_size:
            self._tau_mag_history.pop(0)
        if len(self._tau_z_history) > self._noise_buffer_size:
            self._tau_z_history.pop(0)

        # # Periodically compute and print noise stats
        # self._update_counter += 1
        # if self._update_counter % self._noise_report_interval == 0:
        #     tau_mag_arr = np.array(self._tau_mag_history)
        #     tau_z_arr = np.array(self._tau_z_history)

        #     if tau_mag_arr.size > 1:
        #         mean_mag = np.mean(tau_mag_arr)
        #         std_mag = np.std(tau_mag_arr)
        #         rel_std_mag = (std_mag / mean_mag * 100) if mean_mag != 0 else 0
        #         print(f"[MomentMap] τx/y mean: {mean_mag:.2f}, std: {std_mag:.2f}, rel std: {rel_std_mag:.2f}%")

        #     if tau_z_arr.size > 1:
        #         mean_z = np.mean(tau_z_arr)
        #         std_z = np.std(tau_z_arr)
        #         rel_std_z = (std_z / mean_z * 100) if mean_z != 0 else 0
        #         print(f"[MomentMap] τz mean: {mean_z:.2f}, std: {std_z:.2f}, rel std: {rel_std_z:.2f}%")


    def hideEvent(self, event):
        print("[MomentMap] Window hidden — moment map updates paused.")
        event.accept()

    def closeEvent(self, event):
        print("[MomentMap] Window closed — moment map updates stopped.")
        event.accept()
