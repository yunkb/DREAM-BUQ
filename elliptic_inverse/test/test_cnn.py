"""
This is to test CNN in emulating (extracted) gradients compared with those exactly calculated.
"""

import numpy as np
import dolfin as df
import tensorflow as tf
import sys,os
sys.path.append( "../" , "../../")
from Elliptic import Elliptic
from util.dolfin_gadget import vec2fun,fun2img,img2fun
from nn.cnn import CNN
from tensorflow.keras.models import load_model

# set random seed
np.random.seed(2020)

# define the inverse problem
nx=40; ny=40
SNR=50
elliptic = Elliptic(nx=nx,ny=ny,SNR=SNR)
# algorithms
algs=['EKI','EKS']
num_algs=len(algs)
alg_no=1

# define the emulator (CNN)
# load data
ensbl_sz = 100
folder = '../analysis_f_SNR'+str(SNR)
loaded=np.load(file=os.path.join(folder,algs[alg_no]+'_ensbl'+str(ensbl_sz)+'_training.npz'))
X=loaded['X']
Y=loaded['Y']
# pre-processing: scale X to 0-1
X-=np.nanmin(X,axis=(1,2),keepdims=True) # try axis=(1,2,3)
X/=np.nanmax(X,axis=(1,2),keepdims=True)
X=X[:,:,:,None]
# split train/test
num_samp=X.shape[0]
n_tr=np.int(num_samp*.75)
x_train,y_train=X[:n_tr],Y[:n_tr]
x_test,y_test=X[n_tr:],Y[n_tr:]

# define CNN
num_filters=[16,32]
activations={'conv':'relu','latent':tf.keras.layers.PReLU(),'output':'linear'}
latent_dim=128
droprate=.25
optimizer=tf.keras.optimizers.Adam(learning_rate=0.001)
cnn=CNN(x_train, y_train, num_filters=num_filters, x_test=x_test, y_test=y_test, 
        latent_dim=latent_dim, activations=activations, droprate=droprate, optimizer=optimizer)
try:
    cnn.model=load_model(os.path.join(folder,'cnn_'+algs[alg_no]+'.h5'))
    print('cnn_'+algs[alg_no]+'.h5'+' has been loaded!')
except Exception as err:
    print(err)
    print('Train CNN...\n')
    epochs=100
    import timeit
    t_start=timeit.default_timer()
    cnn.train(epochs,batch_size=64,verbose=1)
    t_used=timeit.default_timer()-t_start
    print('\nTime used for training CNN: {}'.format(t_used))
    # save CNN
#     cnn.model.save('./result/cnn_model.h5')
    cnn.save(folder,'cnn_'+algs[alg_no])
    # how to laod model
#     from tensorflow.keras.models import load_model
#     reconstructed_model=load_model('XX_model.h5')

# some more test
loglik = lambda x: 0.5*elliptic.misfit.prec*tf.math.reduce_sum((cnn.model(x)-elliptic.misfit.obs)**2,axis=1)
import timeit
t_used = np.zeros(2)
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(12,6), facecolor='white')
plt.ion()
# plt.show(block=True)
u_f = df.Function(elliptic.pde.V)
for n in range(10):
    u=elliptic.prior.sample()
    # calculate gradient
    t_start=timeit.default_timer()
    dll_xact = elliptic.get_geom(u,[0,1])[1]
    t_used[0] += timeit.default_timer()-t_start
    # emulate gradient
    t_start=timeit.default_timer()
    u_img=fun2img(vec2fun(u,elliptic.pde.V))
    dll_emul = cnn.gradient(u_img[None,:,:,None], loglik)
    t_used[1] += timeit.default_timer()-t_start
    # test difference
    dif = dll_xact - img2fun(dll_emul,elliptic.pde.V).vector()
    print('Difference between the calculated and emulated gradients: min ({}), med ({}), max ({})'.format(dif.min(),np.median(dif.get_local()),dif.max()))
    
#     # check the gradient extracted from emulation
#     v=elliptic.prior.sample()
#     v_img=fun2img(vec2fun(v,elliptic.pde.V))
#     h=1e-4
#     dll_emul_fd_v=(loglik(u_img[None,:,:,None]+h*v_img[None,:,:,None])-loglik(u_img[None,:,:,None]))/h
#     reldif = abs(dll_emul_fd_v - dll_emul.flatten().dot(v_img.flatten()))/v.norm('l2')
#     print('Relative difference between finite difference and extracted results: {}'.format(reldif))
    
    # plot
    plt.subplot(121)
    u_f.vector().set_local(dll_xact)
    df.plot(u_f)
    plt.title('Calculated Gradient')
    plt.subplot(122)
    u_f=img2fun(dll_emul,elliptic.pde.V)
    df.plot(u_f)
    plt.title('Emulated Gradient')
    plt.draw()
    plt.pause(1.0/10.0)
    
print('Time used to calculate vs emulate gradients: {} vs {}'.format(*t_used.tolist()))