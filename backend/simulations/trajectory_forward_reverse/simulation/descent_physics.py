import math

GRAVITY = 9.80665


class Parachute:

    def __init__(
        self,
        payload_mass,
        parachute_diameter,
        drag_coefficient=1.5
    ):
        self.payload_mass = payload_mass
        self.parachute_diameter = parachute_diameter
        self.drag_coefficient = drag_coefficient

    def area(self):
        radius = self.parachute_diameter / 2.0
        return math.pi * radius**2

    def gravity_force(self):
        return self.payload_mass * GRAVITY

    def drag_force(self, air_density, velocity):
        
        return (
            0.5
            * air_density
            * self.drag_coefficient
            * self.area()
            * velocity
            * abs(velocity)
        )

    def vertical_acceleration(self, air_density, velocity):
       
        weight = self.gravity_force()
        drag = self.drag_force(air_density, velocity)
        return (weight - drag) / self.payload_mass

    def terminal_velocity(self, air_density):
        return math.sqrt((2.0 * self.payload_mass * GRAVITY)/ (air_density * self.drag_coefficient * self.area()))

    def exact_velocity_step(self, air_density, velocity, dt):
        
        if air_density <= 0:
            raise ValueError("air_density must be positive.")

        if dt <= 0:
            return velocity

        vt = self.terminal_velocity(air_density)

        if velocity >= 0:
            x = velocity / vt

            if x < 1.0:
                a = math.atanh(max(min(x, 1.0 - 1e-12), -1.0 + 1e-12))
                return vt * math.tanh(a + (GRAVITY / vt) * dt)
            return vt

        
        t_to_zero = (
            math.atanh(max(min(velocity / vt, 1.0 - 1e-12), -1.0 + 1e-12))* -vt / GRAVITY
        )

        if t_to_zero >= dt:
            a = math.atanh(
                max(min(velocity / vt, 1.0 - 1e-12), -1.0 + 1e-12)
            )
            return vt * math.tanh(
                a + (GRAVITY / vt) * dt
            )

        return self.exact_velocity_step(
            air_density,
            0.0,
            dt - max(t_to_zero, 0.0)
        )

    def exact_distance_step(self, air_density, velocity, dt):
        
        if air_density <= 0:
            raise ValueError("air_density must be positive.")

        if dt <= 0:
            return 0.0

        vt = self.terminal_velocity(air_density)

        if velocity >= 0:
            x = max(min(velocity / vt, 1.0 - 1e-12), -1.0 + 1e-12)
            a = math.atanh(x)
            b = a + (GRAVITY / vt) * dt

            # Integral of v(t) = vt*tanh(a + g*t/vt)
            return (
                (vt * vt / GRAVITY) * (math.log(math.cosh(b))- math.log(math.cosh(a)))
            )

        
        v_mid = self.exact_velocity_step(
            air_density,
            velocity,
            dt / 2.0
        )
        return max(0.0, v_mid * dt)
