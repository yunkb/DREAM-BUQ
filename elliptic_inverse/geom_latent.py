"""
Geometric functions of latent variables, which are encoder outputs,
with geometric quantities emulated or extracted from emulator
------------------------------------------------------------------
Shiwei Lan @ ASU, June 2020
"""

import numpy as np
import dolfin as df
import sys,os
sys.path.append( "../" )
from util.dolfin_gadget import vec2fun,fun2img,img2fun
from util.multivector import *
from util.Eigen import *
from posterior import *

# functions needed to make even image size
def pad(A,width=[1]):
    shape=A.shape
    if len(width)==1: width=np.tile(width,len(shape))
    if not any(width): return A
    assert len(width)==len(shape), 'non-matching padding width!'
    pad_width=tuple((0,i) for i in width)
    return np.pad(A, pad_width)
def chop(A,width=[1]):
    shape=A.shape
    if len(width)==1: width=np.tile(width,len(shape))
    if not any(width): return A
    assert len(width)==len(shape), 'non-matching chopping width!'
    chop_slice=tuple(slice(0,-i) for i in width)
    return A[chop_slice]

def geom(unknown_lat,V_lat,V,autoencoder,geom_ord=[0],whitened=False,**kwargs):
    loglik=None; gradlik=None; metact=None; rtmetact=None; eigs=None
    
#     # un-whiten if necessary
#     if whitened:
#         unknown_lat=bip_lat.prior.v2u(unknown_lat)
    
#     u_latin={'AutoEncoder':unknown_lat.get_local()[None,:],'ConvAutoEncoder':chop(fun2img(vec2fun(unknown_lat, V_lat)))[None,:,:,None]}[type(autoencoder).__name__]
    if type(autoencoder).__name__=='AutoEncoder':
        u_latin=unknown_lat.get_local()[None,:]
        unknown=df.Function(V).vector()
        unknown.set_local(autoencoder.decode(u_latin).flatten())
    elif type(autoencoder).__name__=='ConvAutoEncoder':
        u_latin=fun2img(vec2fun(unknown_lat, V_lat))
        width=tuple(np.mod(i,2) for i in u_latin.shape)
        u_latin=chop(u_latin,width)[None,:,:,None]
        unknown=img2fun(pad(np.squeeze(autoencoder.decode(u_latin)),width),V).vector()
    
    emul_geom=kwargs.pop('emul_geom',None)
    full_geom=kwargs.pop('full_geom',None)
    bip_lat=kwargs.pop('bip_lat',None)
    try:
        if len(kwargs)==0:
            loglik,gradlik,metact_,rtmetact_ = emul_geom(unknown,geom_ord,whitened)
        else:
            loglik,gradlik,metact_,eigs_ = emul_geom(unknown,geom_ord,whitened,**kwargs)
    except:
        try:
            if len(kwargs)==0:
                loglik,gradlik,metact_,rtmetact_ = full_geom(unknown,geom_ord,whitened)
            else:
                loglik,gradlik,metact_,eigs_ = full_geom(unknown,geom_ord,whitened,**kwargs)
        except:
            raise RuntimeError('No geometry in the original space available!')
    
    if any(s>=1 for s in geom_ord):
        jac_=autoencoder.jacobian(u_latin,'decode')
        if type(autoencoder).__name__=='ConvAutoEncoder':
#             jac__=np.zeros(jac_.shape[:2]+tuple(i+1 for i in jac_.shape[2:]))
#             jac__[:,:,:-1,:-1]=jac_; jac_=jac__
            jac_=pad(jac_,(0,)*2+width)
            jac_=jac_.reshape(jac_.shape[:2]+(-1,))
            d2v = df.dof_to_vertex_map(V_lat)
            jac_=jac_[:,:,d2v]
        jac=MultiVector(unknown,V_lat.dim())
#         [jac[i].set_local({'AutoEncoder':jac_[:,i],'ConvAutoEncoder':img2fun(pad(jac_[:,:,i]), V).vector()}[type(autoencoder).__name__]) for i in range(V_lat.dim())] # not working: too many indices?
        if type(autoencoder).__name__=='AutoEncoder':
            [jac[i].set_local(jac_[:,i]) for i in range(V_lat.dim()) for i in range(V_lat.dim())]
        elif type(autoencoder).__name__=='ConvAutoEncoder':
            [jac[i].set_local(img2fun(pad(jac_[:,:,i],width), V).vector()) for i in range(V_lat.dim())]
        gradlik_=jac.dot(gradlik)
        gradlik=df.Vector(unknown_lat)
        gradlik.set_local(gradlik_)
    
    if any(s>=1.5 for s in geom_ord):
        def _get_metact_misfit(u_actedon):
            if type(u_actedon) is df.Vector:
                u_actedon=u_actedon.get_local()
            tmp=df.Vector(unknown); tmp.zero()
            jac.reduce(tmp,u_actedon)
            v=df.Vector(unknown_lat)
            v.set_local(jac.dot(metact_(tmp)))
            return v
        def _get_rtmetact_misfit(u_actedon):
            if type(u_actedon) is not df.Vector:
                u_=df.Vector(unknown)
                u_.set_local(u_actedon)
                u_actedon=u_
            v=df.Vector(unknown_lat)
            v.set_local(jac.dot(rtmetact_(u_actedon)))
            return v
        metact = _get_metact_misfit
        rtmetact = _get_rtmetact_misfit
    
    if any(s>1 for s in geom_ord) and len(kwargs)!=0:
        if bip_lat is None: raise ValueError('No latent inverse problem defined!')
        # compute eigen-decomposition using randomized algorithms
        if whitened:
            # generalized eigen-decomposition (_C^(1/2) F _C^(1/2), M), i.e. _C^(1/2) F _C^(1/2) = M V D V', V' M V = I
            def invM(a):
                a=bip_lat.prior.gen_vector(a)
                invMa=bip_lat.prior.gen_vector()
                bip_lat.prior.Msolver.solve(invMa,a)
                return invMa
            eigs = geigen_RA(metact, lambda u: bip_lat.prior.M*u, invM, dim=bip_lat.pde.V.dim(),**kwargs)
        else:
            # generalized eigen-decomposition (F, _C^(-1)), i.e. F = _C^(-1) U D U^(-1), U' _C^(-1) U = I, V = _C^(-1/2) U
            eigs = geigen_RA(metact,lambda u: bip_lat.prior.C_act(u,-1,op='K'),lambda u: bip_lat.prior.C_act(u,op='K'),dim=bip_lat.pde.V.dim(),**kwargs)
        if any(s>1.5 for s in geom_ord):
            # adjust the gradient
            # update low-rank approximate Gaussian posterior
            bip_lat.post_Ga = Gaussian_apx_posterior(bip_lat.prior,eigs=eigs)
#             Hu = bip_lat.prior.gen_vector()
#             bip_lat.post_Ga.Hlr.mult(unknown, Hu)
#             gradlik.axpy(1.0,Hu)
    
    if len(kwargs)==0:
        return loglik,gradlik,metact,rtmetact
    else:
        return loglik,gradlik,metact,eigs