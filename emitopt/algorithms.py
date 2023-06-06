import copy
from typing import Dict, Optional, Union

import torch
from botorch.models.model import Model

from scipy.optimize import minimize
from torch import Tensor

from .sampling import draw_product_kernel_post_paths, draw_linear_product_kernel_post_paths

from .utils import (
    get_meas_scan_inputs_from_tuning_configs,
    get_valid_emittance_samples,
    post_mean_emit,
    post_path_emit,
    post_path_misalignment,
    sum_samplewise_emittance_flat_X,
    sum_samplewise_misalignment_flat_X
)
from xopt.generators.bayesian.bax.algorithms import Algorithm


def unif_random_sample_domain(n_samples, domain):
    ndim = len(domain)

    # uniform sample, rescaled, and shifted to cover the domain
    x_samples = torch.rand(n_samples, ndim) * torch.tensor(
        [bounds[1] - bounds[0] for bounds in domain]
    ) + torch.tensor([bounds[0] for bounds in domain])

    return x_samples


class ScipyMinimizeEmittance(Algorithm):
    def __init__(
        self,
        beam_energy: float,
        q_len: float,
        distance: float,
        domain: Tensor,  # shape (ndim, 2)
        meas_dim: int,
        n_samples: int,
        n_steps_measurement_param: Optional[int] = 3,
        n_steps_exe_paths: Optional[int] = 50,
        tkwargs: Dict = {"dtype": torch.double, "device": "cpu"},
    ) -> None:
        self.beam_energy = torch.tensor(beam_energy)
        self.q_len = torch.tensor(q_len)
        self.distance = torch.tensor(distance)
        self.domain = torch.tensor(domain)
        self.ndim = domain.shape[0]
        self.n_samples = n_samples
        self.meas_dim = meas_dim
        self.n_steps_measurement_param = n_steps_measurement_param
        self.X_meas = torch.linspace(
            *self.domain[meas_dim], self.n_steps_measurement_param
        )
        self.n_steps_exe_paths = n_steps_exe_paths
        temp_id = self.meas_dim + 1
        self.tuning_domain = torch.cat(
            (self.domain[: self.meas_dim], self.domain[temp_id:])
        )
        self._twkargs = tkwargs

    def get_exe_paths(self, model: Model):
        X_stars_all, emit_stars_all, is_valid, post_paths_cpu = self.get_sample_optimal_tuning_configs(model, cpu=True)

        device = torch.tensor(1).device
        torch.set_default_tensor_type("torch.DoubleTensor")

        # prepare column of measurement scans coordinates
        X_meas_dense = torch.linspace(
            *self.domain[self.meas_dim], self.n_steps_exe_paths
        )

        # expand the X tensor to represent quad measurement scans
        # at the locations in tuning parameter space specified by X
        xs = get_meas_scan_inputs_from_tuning_configs(
            self.meas_dim, X_stars_all, X_meas_dense
        )

        xs_exe = xs.reshape(self.n_samples, self.n_steps_exe_paths, self.ndim)
        
        # evaluate posterior samples at input locations
        ys_exe = post_paths_cpu(xs_exe).reshape(
            self.n_samples, self.n_steps_exe_paths, 1
        )

        if device.type == "cuda":
            torch.set_default_tensor_type("torch.cuda.DoubleTensor")

        if sum(is_valid) < 3:
            print("Scipy failed to find at least 3 physically valid solutions.")
            # no cut
            cut_ids = torch.tensor(range(self.n_samples)) 
        else:
            # only keep the physically valid solutions
            cut_ids = torch.tensor(range(self.n_samples))[is_valid]

        xs_exe = torch.index_select(xs_exe.to(device), dim=0, index=cut_ids)
        ys_exe = torch.index_select(ys_exe.to(device), dim=0, index=cut_ids)
        X_stars = torch.index_select(
            X_stars_all.to(device), dim=0, index=cut_ids
        )
        emit_stars = torch.index_select(
            emit_stars_all.to(device), dim=0, index=cut_ids
        )

        results_dict = {
                        'xs_exe': xs_exe,
                        'ys_exe': ys_exe,
                        'X_stars': X_stars,
                        'emit_stars': emit_stars,
                        'X_stars_all': X_stars_all,
                        'emit_stars_all': emit_stars_all,
                        'is_valid': is_valid,
                        'post_paths_cpu': post_paths_cpu,
                        }
        
        return xs_exe, ys_exe, results_dict

    def get_sample_optimal_tuning_configs(
        self, model: Model, verbose=False, cpu=False
    ):
        device = torch.tensor(1).device
        torch.set_default_tensor_type("torch.DoubleTensor")

        cpu_model = copy.deepcopy(model).cpu()

        post_paths_cpu = draw_product_kernel_post_paths(
            cpu_model, n_samples=self.n_samples
        )

        xs_tuning_init = unif_random_sample_domain(
            self.n_samples, self.tuning_domain
        ).double()

        X_tuning_init = xs_tuning_init.flatten()

        # minimize
        def target_func_for_scipy(X_tuning_flat):
            return (
                sum_samplewise_emittance_flat_X(
                    post_paths_cpu, self.beam_energy.cpu(), self.q_len.cpu(), self.distance.cpu(), 
                    torch.tensor(X_tuning_flat), self.meas_dim,  self.X_meas.cpu()
                )
                .detach()
                .cpu()
                .numpy()
            )

        def target_func_for_torch(X_tuning_flat):
            return sum_samplewise_emittance_flat_X(
                    post_paths_cpu, self.beam_energy.cpu(), self.q_len.cpu(), self.distance.cpu(), 
                    X_tuning_flat, self.meas_dim,  self.X_meas.cpu()
            )
        

        def target_jac(X):
            return (
                torch.autograd.functional.jacobian(
                    target_func_for_torch, torch.tensor(X)
                )
                .detach()
                .cpu()
                .numpy()
            )

        res = minimize(
            target_func_for_scipy,
            X_tuning_init.detach().cpu().numpy(),
            jac=target_jac,
            bounds=self.tuning_domain.repeat(self.n_samples, 1).detach().cpu().numpy(),
            options={"eps": 1e-03},
        )
        if verbose:
            print(
                "ScipyMinimizeEmittance evaluated",
                self.n_samples,
                "(pathwise) posterior samples",
                res.nfev,
                "times in get_sample_optimal_tuning_configs().",
            )

            print(
                "ScipyMinimizeEmittance evaluated",
                self.n_samples,
                "(pathwise) posterior sample jacobians",
                res.njev,
                "times in get_sample_optimal_tuning_configs().",
            )

            print(
                "ScipyMinimizeEmittance took", res.nit, "steps in get_sample_optimal_tuning_configs()."
            )

        x_stars_flat = torch.tensor(res.x)

        X_stars_all = x_stars_flat.reshape(
            self.n_samples, -1
        )  # each row represents its respective sample's optimal tuning config

        emit_stars_all, is_valid = post_path_emit(
            post_paths_cpu,
            self.beam_energy.cpu(), 
            self.q_len.cpu(), 
            self.distance.cpu(),
            X_stars_all,
            self.meas_dim,
            self.X_meas.cpu(),
            samplewise=True,
            squared=False,
        )

        if device.type == "cuda":
            torch.set_default_tensor_type("torch.cuda.DoubleTensor")

        if cpu:
            return X_stars_all, emit_stars_all, is_valid, post_paths_cpu  # X_stars should still be on cpu
        else:
            return X_stars_all.to(device), emit_stars_all.to(device), is_valid.to(device), post_paths_cpu

    def mean_output(self, model, num_restarts=1):
        def target_func_for_scipy(X_tuning_flat):
            return (
                post_mean_emit(
                    model,
                    self.beam_energy,
                    self.q_len,
                    self.distance,
                    torch.tensor(X_tuning_flat).reshape(num_restarts, -1),
                    self.meas_dim,
                    self.X_meas,
                    squared=True
                )[0]
                .flatten()
                .sum()
                .detach()
                .cpu()
                .numpy()
            )

        def target_func_for_torch(X_tuning_flat):
                return (
                post_mean_emit(
                    model,
                    self.beam_energy,
                    self.q_len,
                    self.distance,
                    X_tuning_flat.reshape(num_restarts, -1),
                    self.meas_dim,
                    self.X_meas,
                    squared=True
                    )[0]
                    .flatten()
                    .sum()
                )
        def target_jac(X):
            return (
                torch.autograd.functional.jacobian(
                    target_func_for_torch, torch.tensor(X)
                )
                .detach()
                .cpu()
                .numpy()
            )

        X_tuning_init = (
            unif_random_sample_domain(num_restarts, self.tuning_domain)
            .double()
            .flatten()
        )

        res = minimize(
            target_func_for_scipy,
            X_tuning_init.detach().cpu().numpy(),
            jac=target_jac,
            bounds=self.tuning_domain.repeat(num_restarts, 1).detach().cpu().numpy(),
            #                        tol=1e-5,
            options={"eps": 1e-03},
        )

        X_tuned_candidates = torch.tensor(res.x).reshape(num_restarts, -1)
        min_emit_sq_candidates = post_mean_emit(
            model, self.beam_energy, self.q_len, self.distance, X_tuned_candidates, self.meas_dim, self.X_meas, squared=True
        )[0].squeeze()

        min_emit_sq_id = torch.argmin(min_emit_sq_candidates)

        X_tuned = X_tuned_candidates[min_emit_sq_id].reshape(1, -1)

        (
            emits_at_target_valid,
            emits_sq_at_target,
            is_valid,
            sample_validity_rate,
        ) = get_valid_emittance_samples(
            model,
            self.beam_energy,
            self.q_len,
            self.distance,
            X_tuned,
            self.domain,
            self.meas_dim,
            n_samples=10000,
            n_steps_quad_scan=10,
        )

        return (
            X_tuned,
            emits_at_target_valid,
            emits_sq_at_target,
            is_valid,
            sample_validity_rate,
        )


class ScipyBeamAlignment(Algorithm):
    def __init__(
        self,
        domain: Tensor,  # shape (ndim, 2)
        meas_dims: Union[int, list[int]],
        n_samples: int,
        tkwargs: Dict = {"dtype": torch.double, "device": "cpu"}
    ) -> None:
        super().__init__(domain, n_samples, tkwargs)
        self.meas_dims = meas_dims
        self.meas_scans = torch.index_select(self.domain, dim=0, index=torch.tensor(meas_dims))
        self.tuning_dims = [i for i in range(self.ndim) if i not in self.meas_dims]
        self.tuning_domain = torch.index_select(self.domain, dim=0, index=torch.tensor(self.tuning_dims))

    def get_exe_paths(self, model: Model):
        
        X_stars_all, xs, ys, post_paths_cpu = self.get_sample_optimal_tuning_configs(model, cpu=False)

        xs_exe = xs
        ys_exe = ys.reshape(*ys.shape, 1)
        

        results_dict = {
                        'xs_exe': xs_exe,
                        'ys_exe': ys_exe,
                        'X_stars': X_stars_all,
                        'post_paths_cpu': post_paths_cpu,
                        }
        
        return xs_exe, ys_exe, results_dict

    def get_sample_optimal_tuning_configs(
        self, model: Model, verbose=False, cpu=False
    ):
        device = torch.tensor(1).device
        torch.set_default_tensor_type("torch.DoubleTensor")

        cpu_model = copy.deepcopy(model).cpu()

        post_paths_cpu = draw_linear_product_kernel_post_paths(
            cpu_model, n_samples=self.n_samples
        )

        xs_tuning_init = unif_random_sample_domain(
            self.n_samples, self.tuning_domain
        ).double()

        X_tuning_init = xs_tuning_init.flatten()

        # minimize
        def target_func_for_scipy(X_tuning_flat):
            return (
                sum_samplewise_misalignment_flat_X(post_paths_cpu, 
                                                   torch.tensor(X_tuning_flat), 
                                                   self.meas_dims, 
                                                   self.meas_scans.cpu())
                .detach()
                .cpu()
                .numpy()
            )

        def target_func_for_torch(X_tuning_flat):
            return( 
                sum_samplewise_misalignment_flat_X(post_paths_cpu, 
                                                   X_tuning_flat, 
                                                   self.meas_dims, 
                                                   self.meas_scans.cpu())
                  )

        def target_jac(X):
            return (
                torch.autograd.functional.jacobian(
                    target_func_for_torch, torch.tensor(X)
                )
                .detach()
                .cpu()
                .numpy()
            )

        res = minimize(
            target_func_for_scipy,
            X_tuning_init.detach().cpu().numpy(),
            jac=target_jac,
            bounds=self.tuning_domain.repeat(self.n_samples, 1).detach().cpu().numpy(),
            options={"eps": 1e-03},
        )
        if verbose:
            print(
                "ScipyBeamAlignment evaluated",
                self.n_samples,
                "(pathwise) posterior samples",
                res.nfev,
                "times in get_sample_optimal_tuning_configs().",
            )

            print(
                "ScipyBeamAlignment evaluated",
                self.n_samples,
                "(pathwise) posterior sample jacobians",
                res.njev,
                "times in get_sample_optimal_tuning_configs().",
            )

            print(
                "ScipyBeamAlignment took", res.nit, "steps in get_sample_optimal_tuning_configs()."
            )

        x_stars_flat = torch.tensor(res.x)

        X_stars_all = x_stars_flat.reshape(
            self.n_samples, -1
        )  # each row represents its respective sample's optimal tuning config

        misalignment, xs, ys = post_path_misalignment(post_paths_cpu,
                       X_stars_all, #n x d tensor 
                       self.meas_dims, #list of integers
                       self.meas_scans.cpu(), # tensor of measurement device(s) scan inputs, shape: len(meas_dims) x 2
                       samplewise=True
                       )

        if device.type == "cuda":
            torch.set_default_tensor_type("torch.cuda.DoubleTensor")

        if cpu:
            return X_stars_all, xs, ys, post_paths_cpu  # X_stars should still be on cpu
        else:
            return X_stars_all.to(device), xs.to(device), ys.to(device), post_paths_cpu