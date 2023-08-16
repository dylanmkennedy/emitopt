import torch
from matplotlib import pyplot as plt


def plot_sample_optima_convergence_inputs(results, tuning_parameter_names=None, show_valid_only=True):
    ndim = results[1]["x_stars_all"].shape[1]
    niter = max(results.keys())
    nsamples = results[1]["x_stars_all"].shape[0]

    if tuning_parameter_names is None:
        tuning_parameter_names = ['tp_' + str(i) for i in range(ndim)]

    from matplotlib import pyplot as plt
    
    fig, axs = plt.subplots(ndim, 1)

    for i in range(ndim):

        if ndim > 1:
            ax = axs[i]
        else:
            ax = axs

        ax.set_ylabel(tuning_parameter_names[i])
        ax.set_xlabel("iteration")
        
        if i == 0:
            ax.set_title("Sample Optima Distribution: Tuning Parameters")
            
        for key in results.keys():
            if show_valid_only:
                is_valid = results[key]["is_valid"]
                cut_ids = torch.tensor(range(nsamples))[is_valid]
            else:
                cut_ids = torch.tensor(range(nsamples))
            ax.scatter(torch.tensor([key]).repeat(len(cut_ids)), 
                       torch.index_select(results[key]["x_stars_all"], dim=0, index=cut_ids)[:,i],
                       c='C0')
    plt.tight_layout()


def plot_sample_optima_convergence_emits(results):
    niter = max(results.keys())
    nsamples = results[1]["emit_stars_all"].shape[0]
    
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(1)

    ax.set_ylabel("$\epsilon$")
    ax.set_xlabel("iteration")
    ax.set_title("Sample Optima Distribution: Emittance")
    for key in results.keys():
        is_valid = results[key]["is_valid"]
        valid_ids = torch.tensor(range(nsamples))[is_valid]
        ax.scatter(torch.tensor([key]).repeat(torch.sum(is_valid)), 
                   torch.index_select(results[key]["emit_stars_all"], dim=0, index=valid_ids)[:,0].detach(), 
                   c='C0')
    plt.tight_layout()


def plot_valid_emit_prediction_at_x_tuning(model, 
                                           x_tuning, 
                                           scale_factor, 
                                           q_len, 
                                           distance, 
                                           bounds, 
                                           meas_dim, 
                                           n_samples, 
                                           n_steps_quad_scan):
    (
    emits_at_target_valid,
    sample_validity_rate,
    ) = get_valid_emittance_samples(
            model,
            scale_factor,
            q_len,
            distance,
            x_tuning,
            bounds.T,
            meas_dim,
            n_samples=n_samples,
            n_steps_quad_scan=n_steps_quad_scan,
        )
    
    from matplotlib import pyplot as plt

    plt.hist(emits_at_target_valid.flatten().cpu(), density=True)
    plt.xlabel('Predicted Optimal Emittance')
    plt.ylabel('Probability Density')
    plt.tight_layout()
    plt.show()
    print('sample validity rate:', sample_validity_rate)


def plot_model_cross_section(model, vocs, scan_dict, nx=50, ny=50):
    scan_var_model_ids = {}
    scan_inputs_template = []
    for i, var_name in enumerate(vocs.variable_names):
        if isinstance(scan_dict[var_name], list):
            if len(scan_dict[var_name])!=2:
                raise ValueError("Entries must be either float or 2-element list of floats.")
            scan_var_model_ids[var_name] = i
            scan_inputs_template += [scan_dict[var_name][0]]
        else:
            if not isinstance(scan_dict[var_name],float):
                raise ValueError("Entries must be either float or 2-element list of floats.")
            scan_inputs_template += [scan_dict[var_name]]
    
    if len(scan_var_model_ids)!=2:
        raise ValueError("Exactly 2 keys must have entries that are 2-element lists.")
    
    scan_inputs = torch.tensor(scan_inputs_template).repeat(nx*ny, 1)

    scan_varx = list(scan_var_model_ids.keys())[0]
    scan_vary = list(scan_var_model_ids.keys())[1]

    lsx = torch.linspace(*scan_dict[scan_varx], nx)
    lsy = torch.linspace(*scan_dict[scan_vary], ny)
    meshx, meshy = torch.meshgrid((lsx, lsy), indexing='xy')
    mesh_points_serial = torch.cat((meshx.reshape(-1,1), meshy.reshape(-1,1)), dim=1)
    
    model_idx = scan_var_model_ids[scan_varx]
    scan_inputs[:,model_idx] = mesh_points_serial[:,0]
    
    model_idy = scan_var_model_ids[scan_vary]
    scan_inputs[:,model_idy] = mesh_points_serial[:,1]

    with torch.no_grad():
        posterior = model.posterior(scan_inputs)
        mean = posterior.mean
        var = posterior.variance

    mean = mean.reshape(ny, nx)
    var = var.reshape(ny, nx)
    
    from matplotlib import pyplot as plt

    fig, axs = plt.subplots(2)

    ax = axs[0]
    m = ax.pcolormesh(meshx, meshy, mean)
    ax.set_xlabel(scan_varx)
    ax.set_ylabel(scan_vary)
    ax.set_title('Posterior Mean')
    cbar_m = fig.colorbar(m, ax=ax)
    
    ax = axs[1]
    v = ax.pcolormesh(meshx, meshy, var)
    ax.set_xlabel(scan_varx)
    ax.set_ylabel(scan_vary)
    ax.set_title('Posterior Variance')
    cbar_v = fig.colorbar(v, ax=ax)

    plt.tight_layout()


def plot_pathwise_surface_samples_2d(optimizer): # paper figure
    if ndim==2:

        device = torch.tensor(1).device
        torch.set_default_tensor_type('torch.DoubleTensor')

        fig, axs = plt.subplots(1, 3, subplot_kw={"projection": "3d"})
        fig.set_size_inches(15,10)

        ax = axs[0]

        for s in range(3):

            # plot first 3 beam size surface samples
            xlin, ylin = torch.arange(-3,1,0.05), torch.arange(-40,40, 1.)
            X, Y = torch.meshgrid(xlin, ylin)
            XY = torch.cat((X.reshape(-1,1), Y.reshape(-1,1)), dim=1)
            print(XY.shape)
            Z = optimizer.generator.algorithm_results['post_paths_cpu'](XY)[s].reshape(X.shape).detach()
            cmap='viridis'
            surf = ax.plot_surface(Y, X, Z, cmap=cmap,
                                   linewidth=0, antialiased=True, alpha=0.3, rasterized=True)

            # add orange parabolic highlights
            ax.plot(Y[0,:].numpy(), Z[0,:].numpy(), zs=X[0,0].item(), zdir='y', c='C1', lw=2, zorder=10)
            ax.plot(Y[int(len(Z[0,:])/2),:].numpy(), Z[int(len(Z[0,:])/2),:].numpy(), zs=X[int(len(Z[0,:])/2),0].item(), zdir='y', c='C1', lw=2)
            ax.plot(Y[-1,:].numpy(), Z[-1,:].numpy(), zs=X[-1,0].item(), zdir='y', c='C1', lw=2)




        # plot initial observations
        x0 = torch.tensor(optimizer.data['x0'].values)[:n_obs_init]
        x1 = torch.tensor(optimizer.data['x1'].values)[:n_obs_init]
        y = torch.tensor([item.item() for item in optimizer.data['y'].values])[:n_obs_init]
        ax.scatter(x1.flatten(), x0.flatten(), y.flatten(), marker='o', c='C0', alpha=1, s=80, label='Random (Initial) Observations', zorder=15)

        # plot bax observations
        x0 = torch.tensor(optimizer.data['x0'].values)[n_obs_init:]
        x1 = torch.tensor(optimizer.data['x1'].values)[n_obs_init:]
        y = torch.tensor([item.item() for item in optimizer.data['y'].values])[n_obs_init:]
        ax.scatter(x1.flatten(), x0.flatten(), y.flatten(), marker='o', c='C1', alpha=1, s=80, label='BAX Observations', zorder=15)

        ax.set_title('Beam Size Surface Samples')
        ax.set_ylabel('Tuning Parameter')
        ax.set_xlabel('Measurement Parameter')
        ax.set_zlabel('Beam Size Squared')

        ax.set_ylim(-3, 1)
        ax.set_zlim(0)

        # remove tick labels
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.set_zticklabels([])

        # make the grid lines transparent
        ax.xaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.yaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.zaxis._axinfo["grid"]['color'] =  (1,1,1,0)

        ax.legend()
        ax.dist = 12



        if device.type == "cuda":
            torch.set_default_tensor_type("torch.cuda.DoubleTensor")



        # do a scan (along the tuning dimension) of our emittance predictions
        emit_lowers = torch.tensor([])
        emit_uppers = torch.tensor([])
        emit_meds = torch.tensor([])
        for tuning_param in xlin:
            x_tuning = tuning_param.reshape(1,-1).to(device)
            emits, emit_x, emit_y, sample_validity_rate = get_valid_geo_mean_emittance_samples_thick_quad(bax_model, 
                                                     scale_factor, 
                                                     0.108, 
                                                     2.26, 
                                                     x_tuning, 
                                                     vocs.bounds.T, 
                                                     meas_dim, 
                                                     n_samples=100000, 
                                                     n_steps_quad_scan=10)
            emit_lower = torch.quantile(emits, q=0.025, dim=0)
            emit_upper = torch.quantile(emits, q=0.975, dim=0)
            emit_med = torch.quantile(emits, q=0.5, dim=0)

            emit_lowers = torch.cat((emit_lowers, emit_lower))
            emit_uppers = torch.cat((emit_uppers, emit_upper))
            emit_meds = torch.cat((emit_meds, emit_med))

        #get a few batches of n_samples pathwise sample optima
        x_stars_all = torch.tensor([])
        emit_stars_all = torch.tensor([])
        for i in range(5):
            algo = optimizer.generator.algorithm
            results_dict = algo.get_execution_paths(beam_size_model, torch.tensor(vocs.bounds))[-1]
            x_stars = results_dict['x_stars']
            emit_stars = results_dict['emit_stars'].detach()
            x_stars_all = torch.cat((x_stars_all, x_stars), dim=0)
            emit_stars_all = torch.cat((emit_stars_all, emit_stars), dim=0)

        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import matplotlib.patches as mpatches

        ax = axs[1]

        # plot median emittance curve
        medline, = ax.plot(emit_meds.cpu().numpy(), xlin.numpy(), zs=0, zdir='z', c='g', label='Median')

        opt_cross = ax.scatter(emit_stars_all.flatten().cpu(), x_stars_all.flatten().cpu(), zs=0, zdir='z', marker='x', s=40, c='m', alpha=0.5, label='Sample Optima')

        # plot emittance 95% confidence interval as a Poly3DCollection (ordering of vertices matters)
        verts = (
            [(emit_lowers[i].item(), xlin[i].item(), 0) for i in range(len(xlin))] + 
            [(emit_uppers[i].item(), xlin[i].item(), 0) for i in range(len(xlin))][::-1]
        )
        ax.add_collection3d(Poly3DCollection([verts],color='g', edgecolor='None', alpha=0.5)) # Add a polygon instead of fill_between


        ax.set_xlabel('Emittance')
        ax.set_ylabel('Tuning Parameter')
        ax.set_title('Emittance Measurement Samples')

        ax.set_xlim(0,25)
        ax.set_ylim(-3,1)
        ax.set_zlim(0,1)

        # remove vertical tick marks
        ax.set_zticks([])

        # remove tick labels
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.set_zticklabels([])

        # make the grid lines transparent
        ax.xaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.yaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.zaxis._axinfo["grid"]['color'] =  (1,1,1,0)

        orange_patch = mpatches.Patch(color='g', alpha=0.5, label='95% C.I.')
        ax.legend(handles=[medline, orange_patch, opt_cross])
        ax.dist = 12



        ax = axs[2]
        bins = 10
        freq, edges = torch.histogram(x_stars_all.flatten().cpu(), bins=bins, density=True)
        for i in range(bins):
            uverts = []
            lverts = []
            uverts += [(freq[i].item(), edges[i].item(), 0), (freq[i].item(), edges[i+1].item(), 0)]
            lverts += [(0, edges[i+1].item(), 0), (0, edges[i].item(), 0)]
            verts = uverts + lverts
            ax.add_collection3d(Poly3DCollection([verts],color='m', edgecolor='k')) # Add a polygon instead of fill_between

        ax.set_title('Distribution of Sample Optimal Tuning Parameters')
        ax.set_ylabel('Tuning Parameter')
        ax.set_xlabel('Frequency')

        ax.set_xlim(0,2)
        ax.set_ylim(-3,1)
        ax.set_zlim(0,1)

        # remove vertical tick marks
        ax.set_zticks([])

        # remove tick labels
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.set_zticklabels([])

        # make the grid lines transparent
        ax.xaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.yaxis._axinfo["grid"]['color'] =  (1,1,1,0)
        ax.zaxis._axinfo["grid"]['color'] =  (1,1,1,0)

        ax.dist = 12

        plt.tight_layout()
        plt.savefig('beamsize-surfaces-with-emittance-1.svg', format='svg')
        plt.show()


def plot_pathwise_sample_emittance_minimization_results(optimizer, sid, ground_truth_emittance_fn=None):
    #select sample result
    X_tuned = optimizer.generator.algorithm_results['x_stars'][sid:sid+1, :]
    print('X_tuned =', X_tuned)
    
    from emitopt.utils import post_path_emit_squared_thick_quad

    n_tuning_dims = X_tuned.shape[1]
    fig, axs = plt.subplots(1, n_tuning_dims)
    if n_tuning_dims == 1: axs = [axs]

    fig.set_size_inches(3*(n_tuning_dims), 3)

    meas_dim = optimizer.generator.algorithm.meas_dim
    tuning_dims = list(range(n_tuning_dims + 1))
    tuning_dims.remove(meas_dim)
    for scan_dim in tuning_dims:
                    
        X_tuning_scan = X_tuned.repeat(100,1)
        ls = torch.linspace(*optimizer.vocs.bounds.T[scan_dim],100)
        X_tuning_scan[:,scan_dim] = ls
        X_meas = torch.linspace(*optimizer.vocs.bounds.T[meas_dim],11)

        emit_sq_xy = []
        for post_paths, sign in zip(optimizer.generator.algorithm_results['post_paths_cpu_xy'], [1, -1]):
            emit_sq = post_path_emit_squared_thick_quad(post_paths, 
                                      sign*optimizer.generator.algorithm.scale_factor, 
                                      optimizer.generator.algorithm.q_len, 
                                      optimizer.generator.algorithm.distance, 
                                      X_tuning_scan.cpu(), meas_dim, X_meas.cpu(), samplewise=False)[0]
            emit_sq_xy += [emit_sq]
        geo_mean_emit = torch.sqrt(emit_sq_xy[0].abs().sqrt() * emit_sq_xy[1].abs().sqrt())

        ax = axs[scan_dim]

        if ground_truth_emittance_fn is not None:
            gt_emits, gt_emit_xy = ground_truth_emittance_fn(x_tuning=X_tuning_scan)
            ax.plot(ls, gt_emits, c='k', label='ground truth')
        ax.plot(ls.cpu(), geo_mean_emit[sid].detach().cpu()*1.e-6, label='Sample ' + str(sid))
        ax.axvline(X_tuned[0,scan_dim].cpu(), c='r', label='Sample optimization result')
        ax.axhline(0, c='k', ls='--', label='physical cutoff')

        ax.set_xlabel('tuning param ' + str(scan_dim))

        if scan_dim == 0:
            ax.set_ylabel('$\sqrt{\epsilon_x\epsilon_y}$')
            ax.legend()

    plt.tight_layout()
    plt.show()


from emitopt.utils import post_mean_emit_squared_thick_quad
def plot_posterior_mean_modeled_emittance(optimizer, x_tuning, ground_truth_emittance_fn=None):
    
    
    # get the beam size squared models in x and y
    model = optimizer.generator.train_model()
    bax_model_ids = [optimizer.generator.vocs.output_names.index(name)
                            for name in optimizer.generator.algorithm.model_names_ordered]
    bax_model = model.subset_output(bax_model_ids)
    
    n_tuning_dims = x_tuning.shape[1]
    fig, axs = plt.subplots(1, n_tuning_dims)
    if n_tuning_dims == 1: axs = [axs]

    fig.set_size_inches(3*(n_tuning_dims), 3)

    meas_dim = optimizer.generator.algorithm.meas_dim
    tuning_dims = list(range(n_tuning_dims + 1))
    tuning_dims.remove(meas_dim)
    for scan_dim in tuning_dims:
        X_tuning_scan = x_tuning.repeat(100,1)
        ls = torch.linspace(*optimizer.vocs.bounds.T[scan_dim],100)
        X_tuning_scan[:,scan_dim] = ls
        X_meas = torch.linspace(*optimizer.vocs.bounds.T[meas_dim],11)

        
        emit_sq_xy = []
        for bss_model, sign in zip(bax_model.models, [1,-1]):
            emit_sq = post_mean_emit_squared_thick_quad(
                model=bss_model,
                scale_factor=sign*optimizer.generator.algorithm.scale_factor,
                q_len=optimizer.generator.algorithm.q_len,
                distance=optimizer.generator.algorithm.distance,
                x_tuning=X_tuning_scan.cpu(),
                meas_dim=meas_dim,
                x_meas=X_meas.cpu(),
            )[0]
            emit_sq_xy += [emit_sq]
            
        geo_mean_emit = torch.sqrt(emit_sq_xy[0].abs().sqrt() * emit_sq_xy[1].abs().sqrt())
        ax = axs[scan_dim]

        if ground_truth_emittance_fn is not None:
            gt_emits, gt_emit_xy = ground_truth_emittance_fn(x_tuning=X_tuning_scan)
            ax.plot(ls, gt_emits, c='k', label='ground truth')
            
        ax.plot(ls.cpu(), geo_mean_emit.detach().cpu()*1.e-6, label='GP mean')
        ax.axhline(0, c='k', ls='--', label='physical cutoff')

        ax.set_xlabel('tuning param ' + str(scan_dim))

        if scan_dim == 0:
            ax.set_ylabel('$\sqrt{\epsilon_x\epsilon_y}$')
            ax.legend()

    plt.tight_layout()
    plt.show()

# +
import time
from botorch.optim.optimize import optimize_acqf

def plot_acq_func_opt_results(optimizer):
    start = time.time()
    acq = optimizer.generator.get_acquisition(optimizer.generator.model)
    end = time.time()
    print('get_acquisition took', end-start, 'seconds.')
    
    start = time.time()
    for i in range(1):
        res = optimize_acqf(acq_function=acq,
                            bounds=torch.tensor(optimizer.vocs.bounds),
                            q=1,
                            num_restarts=10,
                            raw_samples=20,
                            options={'maxiter':50}
                           )
    end = time.time()
    print('optimize_acqf took', end-start, 'seconds.')
    
    last_acq = res[0]
    
    ndim = optimizer.vocs.bounds.shape[1]
    fig, axs = plt.subplots(1, ndim)

    fig.set_size_inches(3*(ndim), 3)

    for scan_dim in range(ndim):
        X_scan = last_acq.repeat(100,1)
        ls = torch.linspace(last_acq[0,scan_dim]-1,last_acq[0,scan_dim]+1,100)

        X_scan[:,scan_dim] = ls

        acq_scan = torch.tensor([acq(X.reshape(1,-1)) for X in X_scan]).reshape(-1)

        ax = axs[scan_dim]

        ax.plot(ls.cpu(), acq_scan.detach().cpu())
        ax.axvline(last_acq[0,scan_dim].cpu(), c='r', label='Acquisition Result')


        ax.set_xlabel('Input ' + str(scan_dim))

        if scan_dim == 0:
            ax.set_ylabel('Acquisition Function')
            ax.legend()

    plt.tight_layout()
    plt.show()

# +
from emitopt.utils import get_meas_scan_inputs_from_tuning_configs

def plot_beam_size_squared_at_x_tuning(optimizer, x_tuning):
    meas_dim = optimizer.generator.algorithm.meas_dim
    n_steps_exe_paths = optimizer.generator.algorithm.n_steps_exe_paths
    x_meas = torch.linspace(*optimizer.vocs.bounds.T[meas_dim], n_steps_exe_paths)
    x_meas_scan = get_meas_scan_inputs_from_tuning_configs(meas_dim=meas_dim, x_tuning=x_tuning, x_meas=x_meas)

    # get the beam size squared models in x and y
    model = optimizer.generator.train_model()
    bax_model_ids = [optimizer.generator.vocs.output_names.index(name)
                            for name in optimizer.generator.algorithm.model_names_ordered]
    bax_model = model.subset_output(bax_model_ids)
    labels = ['$\sigma_{x,rms}^2$', '$\sigma_{y,rms}^2$']
    
    for bss_model, label in zip(bax_model.models, labels):
        bss_posterior = bss_model.posterior(x_meas_scan)
        bss_mean = bss_posterior.mean.flatten().detach()
        bss_var = bss_posterior.variance.flatten().detach()
        plt.plot(x_meas, bss_mean.detach(), label=label)
        plt.fill_between(x_meas, (bss_mean-2*bss_var.sqrt()), (bss_mean+2*bss_var.sqrt()), alpha=0.3)
    
    plt.title('Mean-Square Beam Size GP Model Output')
    plt.xlabel('Measurement Quad Focusing Strength ($[k]=m^{-2}$)')
    plt.ylabel('Mean-Square Beam Size (mm)')
    plt.legend()
    print("x_tuning:", x_tuning)