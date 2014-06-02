import numpy as np
from scipy import ndimage
from scipy import stats
#from scipy.stats import multivariate_normal
from pygco import cut_from_graph
from cip_python.utils.weighted_feature_map_densities \
    import ExpWeightedFeatureMapDensity
from cip_python.utils.feature_maps import PolynomialFeatureMap
import nrrd
import pylab as plt
import sys
import gaussian_rician
import math

def segment_chest_with_atlas(likelihoods, priors, normalization_constants):
    """Segment structures using atlas data and likelihoods. 

    Parameters
    ----------
    likelihoods : list of float arrays, shape (L, M, N)
        Likelihood values for each structure of interest
        
    priors : list of float arrays with shape (L, M, N)
        Each structure of interest will be represented by an array having the
	same size as the input image. Every voxel must have a value in the
	interval [0, 1], indicating the probability of that particular
	structure being present at that particular location.
        
    normalization_constants : list of float arrays with shape (L, M, N)
        Constant for each voxel and each class in order to render the output
        a true posterior probability.
        
    Returns
    -------
    label_map : list of integer array, shape (L, M, N)
        Each segmented strcture of interest will be represented by an array 
        with binary labels.
    """
    
    # For all structures of interest, compute the posterior energy 
    print("computing posterior probabilities\n")
    num_classes = np.shape(priors)[0]
    posterior_probabilities = np.zeros(np.shape(priors), dtype=np.float)
    label_map=np.zeros(np.shape(priors), dtype=np.int)
    
    posterior_probabilities = \
       compute_structure_posterior_probabilities(likelihoods, priors, \
                                                  normalization_constants)
      
    
    print("getting graph cuts segmentations\n")
    #  For each structure separately, input the posterior energies into
    # the graph cuts code and obtain a segmentation   
    #f, axarr = plt.subplots(num_classes) 
    #f2, axarr2 = plt.subplots(num_classes) 
    for i in range(num_classes):

        #axarr[i].imshow(np.squeeze(posterior_probabilities[i]), interpolation='nearest')
        #axarr[i].set_title("posterior # "+ str(i))   
        
        integer_precision = 10000    
        class_posterior_energies= (-np.log(np.maximum(posterior_probabilities[i],0.0000000000001))* \
          integer_precision).astype(np.int32)
          
        not_class_posteriors = np.ones_like(posterior_probabilities[i]).astype(np.float)-\
            posterior_probabilities[i]
          
        not_class_posterior_energies = ( -np.log(np.maximum(not_class_posteriors,0.0000000000001))*integer_precision).astype(np.int32)
          
        label_map[i]=obtain_graph_cuts_segmentation( \
          not_class_posterior_energies, class_posterior_energies)
          
    #    axarr2[i].imshow(np.squeeze(label_map[i]), interpolation='nearest')
    #    axarr2[i].set_title("labelmap # "+ str(i))           
    #plt.show() 

    for i in range(0, num_classes):
        label_map[i] = ndimage.binary_fill_holes(label_map[i]).astype(int)
        label_map[i] = ndimage.binary_fill_holes(label_map[i]).astype(int)              

    return label_map, posterior_probabilities

def segment_lung_with_atlas_gaussian(input_image, probabilistic_atlases, gauss_parameters): 
    #TODO: and command line option to this command
    
    """Segment lung using training labeled data. 

    Parameters
    ----------
    input_image : float array, shape (L, M, N)

    probabilistic_atlases : list of float arrays, shape (L, M, N)
        Atlas to use as segmentation prior. Each voxel should have a value in
        the interval [0, 1], indicating the probability of the class.
        
    gauss_parameters: Parameters of the lileihood gaussian distribution
        ...
        
    Returns
    -------
    label_map : array, shape (L, M, N)
        Segmented image with labels adhering to CIP conventions
    """
    
    length  = np.shape(probabilistic_atlases[0])[0]
    width = np.shape(probabilistic_atlases[0])[1]
    
    #Define lung area to segment
    lungPrior = probabilistic_atlases[0].astype(np.float) + probabilistic_atlases[1].astype(np.float)
    zero_indeces_thresholding = lungPrior < 0.35 
    lungPriorSlicedialated = lungPrior
    lungPriorSlicedialated[zero_indeces_thresholding] = 0.0
    
    ones_indeces_thresholding = lungPrior > 0.34 
    lungPriorSlicedialated[ones_indeces_thresholding] = 1.0

    lungPriorSlicedialated = ndimage.binary_dilation(lungPriorSlicedialated, \
      iterations=2)
    ndimage.morphology.binary_fill_holes(lungPriorSlicedialated, \
      structure=None, output=lungPriorSlicedialated, origin=0)
    tozero_indeces_intensities = lungPriorSlicedialated < 1
    
    
    leftLungMean = np.array([gauss_parameters[0]])
    leftLungCovariance = np.matrix([[ gauss_parameters[1]]])
    notLungMean = np.array([ gauss_parameters[2]])
    notLungCovariance= np.matrix([[gauss_parameters[3] ]])
    rightLungMean = np.array([gauss_parameters[4]])
    rightLungCovariance = np.matrix([[gauss_parameters[5] ]])

   
    left_likelihood = stats.norm.pdf(input_image.astype(np.float), loc=leftLungMean, scale=leftLungCovariance)
    notLungLikelihood = stats.norm.pdf(input_image.astype(np.float), loc=notLungMean, scale=notLungCovariance)
    right_likelihood = stats.norm.pdf(input_image.astype(np.float), loc=leftLungMean, scale=leftLungCovariance)
       
    notLungPrior = np.ones((length, width,np.shape(probabilistic_atlases[0])[2])).astype(np.float)
    notLungPrior = notLungPrior.astype(np.float) - (np.add(probabilistic_atlases[0].astype(np.float), probabilistic_atlases[1].astype(np.float)));
    
    cap_not_lung = (notLungPrior<0)
    notLungPrior[cap_not_lung]=0
    
    ones_indeces_notprior= notLungPrior > 100.0
    notLungPrior[ones_indeces_notprior]=100
       
    p_I_dleft = np.add(np.multiply(left_likelihood.astype(np.float), \
         lungPrior.astype( \
         np.float)),np.multiply(notLungLikelihood.astype(np.float), \
         notLungPrior.astype(np.float)))  
         
    p_I_dright = np.add(np.multiply(left_likelihood.astype(np.float), \
         lungPrior.astype( \
         np.float)),np.multiply(notLungLikelihood.astype(np.float), \
         notLungPrior.astype(np.float)))  
         
    zero_indeces = (p_I_dleft == 0)
    p_I_dleft[zero_indeces] = 0.000000000000000000000001
   
    zero_indeces2 = (p_I_dright == 0)
    p_I_dright[zero_indeces2] = 0.000000000000000000000001
    
    left_likelihood[tozero_indeces_intensities]=0
    right_likelihood[tozero_indeces_intensities]=0
    
    #debugging purposes
    leftLungPosterior = np.divide(np.multiply(probabilistic_atlases[0].astype(np.float),left_likelihood.astype(np.float)),p_I_dleft.astype(np.float))  
    rightLungPosterior = np.divide(np.multiply(probabilistic_atlases[1].astype(np.float),right_likelihood.astype(np.float)),p_I_dleft.astype(np.float))  
    notLungPosterior = np.multiply(notLungLikelihood.astype(np.float),notLungPrior.astype(np.float))   
    
    #segment given feature vectors
    segmented_labels= segment_chest_with_atlas([left_likelihood.astype( \
       np.float), left_likelihood.astype(np.float)], probabilistic_atlases, \
       [p_I_dleft.astype(np.float), p_I_dright.astype(np.float)])
    
    return segmented_labels
    
def segment_lung_with_atlas(input_image, probabilistic_atlases, exponential_parameters): 
    #TODO: and command line option to this command
    
    """Segment lung using training labeled data. 

    Parameters
    ----------
    input_image : float array, shape (L, M, N)

    probabilistic_atlases : list of float arrays, shape (L, M, N)
        Atlas to use as segmentation prior. Each voxel should have a value in
        the interval [0, 1], indicating the probability of the class.
        
    exponential_parameters: Parameters of the exponential likelihood distribution
        ...
        
    Returns
    -------
    label_map : array, shape (L, M, N)
        Segmented image with labels adhering to CIP conventions
    """
    
    #compute feature vectors for left and right lungs
    ### TODO: replace with likelihood params for class 0.


    length  = np.shape(probabilistic_atlases[0])[0]
    width = np.shape(probabilistic_atlases[0])[1]
    
    #Define lung area to segment
    lungPrior = probabilistic_atlases[0] + probabilistic_atlases[1]
    zero_indeces_thresholding = lungPrior < 0.35 
    lungPriorSlicedialated = lungPrior
    lungPriorSlicedialated[zero_indeces_thresholding] = 0.0
    
    ones_indeces_thresholding = lungPrior > 0.34 
    lungPriorSlicedialated[ones_indeces_thresholding] = 1.0

    lungPriorSlicedialated = ndimage.binary_dilation(lungPriorSlicedialated, \
      iterations=2)
    ndimage.morphology.binary_fill_holes(lungPriorSlicedialated, \
      structure=None, output=lungPriorSlicedialated, origin=0)
    tozero_indeces_intensities = lungPriorSlicedialated < 1
    
    
    left_lung_distance_map = compute_distance_to_atlas(probabilistic_atlases[0])   
    right_lung_distance_map = compute_distance_to_atlas(probabilistic_atlases[1])
       
        
    left_polynomial_feature_map = PolynomialFeatureMap( [input_image, \
      left_lung_distance_map],[0,1,2] )  
    left_polynomial_feature_map.compute_num_terms()
    
    right_polynomial_feature_map = PolynomialFeatureMap( [input_image, \
      right_lung_distance_map],[0,1,2] )  
    right_polynomial_feature_map.compute_num_terms()

    #define the weights
    
    #exp(-(alpha(1)*Ival + alpha_(2)*Dval+alpha(3)))^2
    # = exp(-(alpha(1)^2*Ival^2 + alpha(1)*Ival*alpha(2)*Dval  \
    #    +    alpha(1)*Ival*alpha(3) +  alpha(2)*Dval * alpha(1)*Ival
    #    +alpha(2)*Dval*alpha(2)*Dval+alpha(2)*Dval *alpha(3)  \
    #    +  alpha(3)*alpha(1)*Ival+  alpha(3)*alpha(2)*Dval+alpha(3)*alpha(3)))
    
    # = exp(-(alpha(3)*alpha(3) + 2*alpha(1)*alpha(3)*Ival  \
    #    + 2*alpha(2)*alpha(3)*Dval + alpha(1)^2*Ival^2 \ 
    #    + 2* alpha(1)*alpha(2)*Ival*Dval + alpha(2)^2*dval^2 )) 
    
    
    #ExpWeightedFeatureMapDensity computations: 
    #accum = sum_d( \
    #  self.weights[d]*self.feature_map.get_mapped_feature_vec_element(d))
    #exponential_density = np.exp(-self.lamda*accum)*self.lamda
    
    #older weights
    #left_weights_temp = [0.002149, -0.002069, 5.258745] 
    #l_alpha_est_right=[0.001241, -0.025153, 4.609616]      
    #l_alpha_est_non=[-0.001929, 0.010123, 3.937502]  
    #
    #right_weights_temp = [0.002149, -0.002069, 5.258745] 
    #r_alpha_est_left=[0.001241, -0.025153, 4.609616]      
    #r_alpha_est_non=[-0.001929, 0.010123, 3.937502]  
        
    #r_alpha_est_left=[0.002500, -0.095894, 6.786622]
    #right_weights_temp=[0.001245, 0.066628, 4.269774]
    #r_alpha_est_non=[-0.001433, -0.005590, 4.143140]
    
    
    #newer 

#    left_weights_temp=[0.002242, 0.002139, 5.305966]
#    l_alpha_est_right=[0.001987, -0.054164, 5.415881]
#    l_alpha_est_non=[-0.001288, -0.034694, 4.225687]
#
#    r_alpha_est_left=[0.002209, -0.094936, 6.731629]
#    right_weights_temp=[0.001689, 0.072709, 4.398574]
#    r_alpha_est_non=[-0.000816, -0.035418, 4.499488]
    

    #newer, 80 bins instead of 50: left works, right doesnt
    #left_weights_temp=[0.002312, 0.002666, 5.806209]
    #l_alpha_est_right=[0.001729, -0.029253, 5.383404]
    #l_alpha_est_non=[-0.001127, 0.009051, 4.617099]
    #
    #r_alpha_est_left=[0.001914, -0.060901, 6.623247]
    #right_weights_temp=[0.001878, 0.073107, 5.053620]
    #r_alpha_est_non=[-0.000779, -0.029794, 5.143489]




    #l_alpha_est_right=[0.001816, 0.001857, 5.921779]
    #left_weights_temp=[0.002463, 0.118871, 5.827013]
    #l_alpha_est_non=[-0.000091, 0.012917, 4.446526]
    #right_weights_temp=[0.001594, 0.030955, 5.626165] #this is the source of the problemmmm
    #r_alpha_est_left=[0.001946, 0.009239, 5.685427]
    #r_alpha_est_non=[-0.000090, 0.014221, 4.432606]

    #below working
    #alpha_dleft_given_left = [0.002149, -0.002069, 5.258745] 
    #alpha_dleft_given_right=[0.001241, -0.025153, 4.609616]      
    #alpha_dleft_given_non=[-0.001929, 0.010123, 3.937502]  
    ##
    #alpha_dright_given_right = [0.002149, -0.002069, 5.258745] 
    #alpha_dright_given_left=[0.001241, -0.025153, 4.609616]      
    #alpha_dright_given_non=[-0.001929, 0.010123, 3.937502]  
        
    alpha_dleft_given_left = exponential_parameters[0]
    alpha_dleft_given_right=exponential_parameters[1]      
    alpha_dleft_given_non=exponential_parameters[2] 
    #
    alpha_dright_given_right = exponential_parameters[3]
    alpha_dright_given_left=exponential_parameters[4]     
    alpha_dright_given_non=exponential_parameters[5]  


    left_weights = [alpha_dleft_given_left[2]*alpha_dleft_given_left[2], \
                   2*alpha_dleft_given_left[0]*alpha_dleft_given_left[2], \
                    2*alpha_dleft_given_left[1]*alpha_dleft_given_left[2], \
                    alpha_dleft_given_left[0]*alpha_dleft_given_left[0], \
                    2*alpha_dleft_given_left[0]*alpha_dleft_given_left[1], \
                    alpha_dleft_given_left[1]*alpha_dleft_given_left[1] ]
    left_lambda = 1.0
    left_weighted_density = ExpWeightedFeatureMapDensity([\
       input_image.astype(np.float),left_lung_distance_map], left_weights, \
       left_polynomial_feature_map, left_lambda)
    left_likelihood = left_weighted_density.compute()
    
    

    left_weights_given_right = [alpha_dleft_given_right[2]*alpha_dleft_given_right[2], \
                    2*alpha_dleft_given_right[0]*alpha_dleft_given_right[2], \
                    2*alpha_dleft_given_right[1]*alpha_dleft_given_right[2], \
                    alpha_dleft_given_right[0]*alpha_dleft_given_right[0], \
                    2*alpha_dleft_given_right[0]*alpha_dleft_given_right[1], \
                    alpha_dleft_given_right[1]*alpha_dleft_given_right[1] ]
    left_given_right_weighted_density = ExpWeightedFeatureMapDensity([\
       input_image.astype(np.float),left_lung_distance_map], 
       left_weights_given_right, left_polynomial_feature_map, left_lambda)
    LdIgivenRlung = left_given_right_weighted_density.compute()
    
    left_weights_given_nonlung = [alpha_dleft_given_non[2]*alpha_dleft_given_non[2], \
                    2*alpha_dleft_given_non[0]*alpha_dleft_given_non[2], \
                    2*alpha_dleft_given_non[1]*alpha_dleft_given_non[2], \
                    alpha_dleft_given_non[0]*alpha_dleft_given_non[0], \
                    2*alpha_dleft_given_non[0]*alpha_dleft_given_non[1], \
                    alpha_dleft_given_non[1]*alpha_dleft_given_non[1] ]
    left_given_nonlung_weighted_density = ExpWeightedFeatureMapDensity([ \
      input_image.astype(np.float),left_lung_distance_map], \
      left_weights_given_nonlung, left_polynomial_feature_map, left_lambda)
    LdIgivenNlung = left_given_nonlung_weighted_density.compute()
    
    
    
    right_weights = [alpha_dright_given_right[2]*alpha_dright_given_right[2], \
                    2*alpha_dright_given_right[0]*alpha_dright_given_right[2], \
                    2*alpha_dright_given_right[1]*alpha_dright_given_right[2], \
                    alpha_dright_given_right[0]*alpha_dright_given_right[0], \
                    2*alpha_dright_given_right[0]*alpha_dright_given_right[1], \
                    alpha_dright_given_right[1]*alpha_dright_given_right[1] ]
    right_lambda = 1.0
    right_weighted_density = ExpWeightedFeatureMapDensity([input_image, \
           right_lung_distance_map], right_weights, \
           right_polynomial_feature_map, right_lambda)
    right_likelihood = right_weighted_density.compute()
    
    
    right_weights_given_left = [alpha_dright_given_left[2]*alpha_dright_given_left[2], \
                    2*alpha_dright_given_left[0]*alpha_dright_given_left[2], \
                    2*alpha_dright_given_left[1]*alpha_dright_given_left[2], \
                    alpha_dright_given_left[0]*alpha_dright_given_left[0], \
                    2*alpha_dright_given_left[0]*alpha_dright_given_left[1], \
                    alpha_dright_given_left[1]*alpha_dright_given_left[1] ]
    right_lambda = 1.0
    right_given_leftlung_weighted_density = ExpWeightedFeatureMapDensity( \
          [input_image,right_lung_distance_map], right_weights_given_left, \
          right_polynomial_feature_map, right_lambda)
    RdIgivenLlung = right_given_leftlung_weighted_density.compute()
    
    right_weights_given_non = [alpha_dright_given_non[2]*alpha_dright_given_non[2], \
                    2*alpha_dright_given_non[0]*alpha_dright_given_non[2], \
                    2*alpha_dright_given_non[1]*alpha_dright_given_non[2], \
                    alpha_dright_given_non[0]*alpha_dright_given_non[0], \
                    2*alpha_dright_given_non[0]*alpha_dright_given_non[1], \
                    alpha_dright_given_non[1]*alpha_dright_given_non[1] ]
    right_lambda = 1.0
    right_given_nonlung_weighted_density = ExpWeightedFeatureMapDensity( \
         [input_image,right_lung_distance_map], right_weights_given_non, \
         right_polynomial_feature_map, right_lambda)
    RdIgivenNlung = right_given_nonlung_weighted_density.compute()

    
    notLungPrior = np.ones((length, width,np.shape( \
         probabilistic_atlases[0])[2])).astype(np.float)
    notLungPrior = notLungPrior - np.add(probabilistic_atlases[0], \
         probabilistic_atlases[1]);
    
    p_I_dleft = np.add(np.multiply(left_likelihood.astype(np.float), \
         probabilistic_atlases[0].astype(np.float)),np.multiply( \
         LdIgivenRlung.astype(np.float),probabilistic_atlases[1].astype( \
         np.float)),np.multiply(LdIgivenNlung.astype(np.float), \
         notLungPrior.astype(np.float)))  
         
         
    p_I_dright = np.add(np.multiply(RdIgivenLlung.astype(np.float), \
         probabilistic_atlases[0].astype(np.float)),np.multiply( \
         right_likelihood.astype(np.float), \
         probabilistic_atlases[1].astype(np.float)),np.multiply( \
         RdIgivenNlung.astype(np.float),notLungPrior.astype(np.float)))  
    
    zero_indeces = (p_I_dleft == 0)
    p_I_dleft[zero_indeces] = 0.000000000000000000000001
   
    zero_indeces2 = (p_I_dright == 0)
    p_I_dright[zero_indeces2] = 0.000000000000000000000001
    
    left_likelihood[tozero_indeces_intensities]=0
    right_likelihood[tozero_indeces_intensities]=0
    

    #segment given feature vectors
    segmented_labels = segment_chest_with_atlas([left_likelihood.astype( \
       np.float), right_likelihood.astype(np.float)], probabilistic_atlases, \
       [p_I_dleft.astype(np.float), p_I_dright.astype(np.float)])
    
    return segmented_labels
  

def segment_pec_with_atlas(input_image, probabilistic_atlases, alpha_p_distance_given_class, d0params, nonpec_classifier_params, non_diagonals_classifier_params, PecClasses, AllClasses): 
    #TODO: and command line option to this command
    
    """Segment pecs using training labeled data. 

    Parameters
    ----------
    input_image : float array, shape (L, M, N)

    probabilistic_atlases : list of float arrays, shape (L, M, N)
        Atlas to use as segmentation prior. Each voxel should have a value in
        the interval [0, 1], indicating the probability of the class.
        
    exponential_parameters: Parameters of the exponential likelihood distribution
        ...
        
    Returns
    -------
    label_map : array, shape (L, M, N)
        Segmented image with labels adhering to CIP conventions
    """
    
    #compute feature vectors for left and right lungs
    ### TODO: replace with likelihood params for class 0.

    length  = np.shape(probabilistic_atlases["leftmajor"])[0]
    width = np.shape(probabilistic_atlases["leftmajor"])[1]
    
    #this needs to change to be intensity threshold dependent
    
    #tozero_indeces_intensities = (input_image > 90)  & (input_image < -50)
           
    distance_maps = dict()
    likelihoods = dict()
    marginals = dict()
    
    f, axarr = plt.subplots(len(PecClasses), len(AllClasses)) 

    i=0
    j=0 
    
    
  
    for class_index in PecClasses:
        distance_maps[class_index] = compute_distance_to_atlas(probabilistic_atlases[class_index].astype(float))
  
    #p(I,d = distclass_index | givenclass_index)
    for distclass_index in PecClasses:
 
        for givenclass_index in AllClasses:
            if(distclass_index == givenclass_index):                           
                likelihoods[distclass_index, givenclass_index]= compute_gauss_intensities_exp_distance_likelihood(input_image, distance_maps[distclass_index] , alpha_p_distance_given_class[distclass_index, givenclass_index], d0params[distclass_index, givenclass_index]) 
            elif(givenclass_index == "nonpec"):
                likelihoods[distclass_index, givenclass_index] = compute_non_pec_likelihood(input_image, distance_maps[distclass_index], nonpec_classifier_params[distclass_index, givenclass_index])   
            else:
                likelihoods[distclass_index, givenclass_index]= gaussian_rician.gauss_noncentered_rician_pdf(input_image, distance_maps[distclass_index], non_diagonals_classifier_params[distclass_index, givenclass_index])                 

            #im=axarr[i, j].imshow(np.squeeze(likelihoods[distclass_index, givenclass_index]), interpolation='nearest')
            #axarr[i, j].set_title(distclass_index +'| '+givenclass_index)
            ### show range
            j=j+1
        i=i+1
        j=0  
    #cax = f.add_axes([0.2, 0.08, 0.6, 0.04])
    #f.colorbar(im, cax, orientation='horizontal')
    #
    #plt.show() 
    #
    #Add up all distclass likelihoods for a given class
    likelihoods_sum = dict()
    for givenclass_index in AllClasses:
        likelihoods_sum[givenclass_index]=np.zeros_like(likelihoods["leftmajor", givenclass_index]).astype(np.float)
        for distclass_index in PecClasses:           
            likelihoods_sum[givenclass_index] = np.add(likelihoods_sum[givenclass_index],likelihoods[distclass_index, givenclass_index])
        likelihoods_sum[givenclass_index] = np.multiply(likelihoods[distclass_index, givenclass_index], 0.25) 
    
    
    
    
    #f.savefig('/Users/rolaharmouche/Documents/Data/distributions/conditional_distributions.pdf') 
    
    #normalize likelihoods: for a specific (I,d), all |class should be in same range
    #for distclass_index in PecClasses:
    #for distclass_index in PecClasses:
    #    max_all = 0
    #    for givenclass_index in AllClasses:
    #        if (likelihoods[distclass_index, givenclass_index].max() > max_all):
    #            max_all = likelihoods[distclass_index, givenclass_index].max()   
    #    
    #    for givenclass_index in AllClasses:          
    #        print(max_all)
    #        print(likelihoods[distclass_index, givenclass_index].max())
    #        likelihoods[distclass_index, givenclass_index] = likelihoods[distclass_index, givenclass_index] * (max_all/(likelihoods[distclass_index, givenclass_index].max()) )
            
    pec_prior = np.zeros((length, width,1)).astype(np.float)
    for class_index in PecClasses:
        pec_prior = np.add(pec_prior,probabilistic_atlases[class_index].astype(np.float))

    distance_map_prior = compute_distance_to_atlas(pec_prior)

    #threshold

    probabilistic_atlases["nonpec"] = np.ones((length, width,1)).astype(np.float)
    probabilistic_atlases["nonpec"] = probabilistic_atlases["nonpec"].astype(np.float) - pec_prior.astype(np.float);

    probabilistic_atlases["nonpec"][(probabilistic_atlases["nonpec"]<0)] = 0
    probabilistic_atlases["nonpec"][(probabilistic_atlases["nonpec"]>1)] = 1

    #f_mar, axarr = plt.subplots(len(PecClasses)) 
    #i=0

    marginal = np.zeros_like(likelihoods_sum["nonpec"]).astype(np.float)#((length, width,1)).astype(np.float)
    for givenclass_index in AllClasses:
        marginal = np.add(marginal,\
            np.multiply(likelihoods_sum[givenclass_index], \
            probabilistic_atlases[givenclass_index])) 
            
   
#   # #p(I,d = distclass_index )
#    for distclass_index in PecClasses:
#        #marginals[distclass_index]= np.zeros_like(likelihoods[distclass_index, "nonpec"]).astype(np.float)#((length, width,1)).astype(np.float)
#        #for givenclass_index in AllClasses:
#        #    marginals[distclass_index] = np.add(marginals[distclass_index],\
#        #        np.multiply(likelihoods[distclass_index, givenclass_index], \
#        #        probabilistic_atlases[givenclass_index])) 
#        #zero_indeces = (marginals[distclass_index] == 0)
#        ##marginals[distclass_index][zero_indeces] = 0.000000000000000000000001
#        
#        print("max,min marginals for: "+distclass_index+": "+\
#            str(marginal.max())+", "+str(marginal.min()))
#
##        im2 = axarr[i].imshow(np.squeeze(probabilistic_atlases[distclass_index]), interpolation='nearest')
##        axarr[i].set_title(distclass_index+ "  marginals" )
##        i=i+1
##        
##    cax2 = f_mar.add_axes([0.2, 0.08, 0.6, 0.04])
##    f_mar.colorbar(im2, cax2, orientation='horizontal')
##
##    plt.show() 
#



#            
    ## save the likelihoods
    #likelihood_filename = dict()
    #for class_index in PecClasses:
    #    likelihood_filename[class_index] = "/Users/rolaharmouche/Documents/Data/COPDGene/10004O/10004O_INSP_STD_BWH_COPD/10004O_INSP_STD_BWH_COPD_"+class_index+"_likelihood.nrrd"     
    #    nrrd.write(likelihood_filename[class_index],likelihoods[class_index,class_index])               
    #for class_index in PecClasses:     
    #    likelihoods[class_index,class_index][tozero_indeces_intensities]=0 

    #segment given feature vectors
    #segmented_labels = segment_chest_with_atlas([likelihoods["leftmajor", "leftmajor"].astype( \
    #   np.float), likelihoods["leftminor", "leftminor"].astype(np.float),\
    #   likelihoods["rightmajor", "rightmajor"].astype(np.float), \
    #   likelihoods["rightminor", "rightminor"].astype(np.float)], \
    #   [probabilistic_atlases["leftmajor"],probabilistic_atlases["leftminor"],\
    #   probabilistic_atlases["rightmajor"],probabilistic_atlases["rightminor"]     ], \
    #   [marginals["leftmajor"].astype(np.float), marginals["leftminor"].astype(np.float),\
    #   marginals["rightmajor"].astype(np.float), marginals["rightminor"].astype(np.float)])
    
       
    segmented_labels, posteriors= segment_chest_with_atlas([likelihoods_sum["leftmajor"].astype( \
       np.float), likelihoods_sum["leftminor"].astype(np.float),\
       likelihoods_sum["rightmajor"].astype(np.float), \
       likelihoods_sum["rightminor"].astype(np.float)], \
       [probabilistic_atlases["leftmajor"],probabilistic_atlases["leftminor"],\
       probabilistic_atlases["rightmajor"],probabilistic_atlases["rightminor"]     ], \
       [marginal,marginal,marginal,marginal])

    return segmented_labels, posteriors
            
def compute_structure_posterior_probabilities(likelihoods, priors, \
    normalization_constants):
    """Computes the posterior energy given a list of structure likelihoods
       and priors.  

    Parameters
    ----------
    priors : list of float arrays with shape (L, M, N)
        Each structure of interest will be represented by an array having the
	same size as the input image. Every voxel must have a value in the
	interval [0, 1], indicating the probability of that particular
	structure being present at that particular location.

    likelihoods : List WeightedFeatureMapDensity class instances
    
    normalization_constants : list of float arrays with shape (L, M, N)
        constant for each voxel and each class in order to render the output
        a true posterior probability.
        ...
        
    Returns
    -------
    energies : List of float arrays with shape (L, M, N) representing posterior 
              energies for each structure/non structure
    """
    
    #get the number of classes, initialize list of posteriors
    num_classes = np.shape(likelihoods)[0] 
    assert num_classes == np.shape(priors)[0] 
    
    # make sure none of the normalization value are = 0
    #for d in range(0, num_classes):
    #    assert (normalization_constants.all() != 0)
    
    posteriors = np.zeros(np.shape(likelihoods))
    
    for d in range(0, num_classes):
        #create a mask for when the likelihoods are really low
        zero_indeces = (normalization_constants[0] < 0.000001)
        normalization_constants[d][zero_indeces] = 0.0000000000000000001#*np.max(likelihoods[d])  
        threashold = 0.000000001*np.max(likelihoods[d])        
        posteriors[d] = likelihoods[d].astype(np.float)*priors[d].astype(np.float) /(normalization_constants[d]).astype(np.float)
        #mask = (posteriors[d]<threashold)
        
        #mask2 =(posteriors[d] <0) 
        #posteriors[d][mask2]=0
        posteriors[d][zero_indeces]=0;
        
        #mask3 =(posteriors[d] >1) 
        #posteriors[d][mask3]=1
        #posteriors[d][mask] = 0
    return posteriors
    
def obtain_graph_cuts_segmentation(structure_posterior_energy, \
     not_structure_posterior_energy):
    """Obtains the graph cuts segmentation for a structure given the posterior 
       energies.  
    
    Parameters
    ----------
    structure_posterior_energy: A float array with shape (L, M, N) 
            representing the posterior energies for the structure of interest. 
            (source) 
    not_structure_posterior_energy :  A float array with shape (L, M, N) 
            representing the posterior energies for not being the structure
            of interest. (sink)
        ...
        
    Returns
    -------
    label_map : array, shape (L, M, N)
        Segmented image with labels adhering to CIP conventions
    """

    length = np.shape(structure_posterior_energy)[0];
    width = np.shape(structure_posterior_energy)[1];
    if (np.size(np.shape(structure_posterior_energy)[1]) == 3):
        num_slices = np.shape(structure_posterior_energy)[2];
    else:
        num_slices = 1 
        
    numNodes = length * width
    segmented_image = np.zeros((length, width, num_slices), dtype = np.int32)
    
    for slice_num in range(0, num_slices):
        print("graph cut slice" +str(slice_num))
        source_slice = structure_posterior_energy[:,:,slice_num: \
           (slice_num+1)].squeeze().astype(np.int32) 
        sink_slice = not_structure_posterior_energy[:,:,slice_num: \
           (slice_num+1)].squeeze().astype(np.int32) 

        imageIndexArray =  np.arange(numNodes).reshape(np.shape( \
           source_slice)[0], np.shape(source_slice)[1])
 
        #Adding neighbourhood terms 
        inds = np.arange(imageIndexArray.size).reshape(imageIndexArray.shape) 
        #goes from [[0,1,...numcols-1],[numcols, ...],..[.., num_elem-1]]
        horz = np.c_[inds[:, :-1].ravel(), inds[:, 1:].ravel()] 
        #all rows, not last col make to 1d
        vert = np.c_[inds[:-1, :].ravel(), inds[1:, :].ravel()] 
        #all rows, not first col, make to 1d
        edges = np.vstack([horz, vert]).astype(np.int32) 
        #horz is first element, vert is 
        theweights = np.ones((np.shape(edges))).astype(np.int32) ##*18
        edges = np.hstack((edges,theweights))[:,0:3].astype(np.int32) 
        #stack the weight value hor next to edge indeces
    
    #    #3rd order neighbours, good for lung
    #    horz = np.c_[inds[:, :-2].ravel(), inds[:,2:].ravel()] 
    #    #all rows, not last col make to 1d
    #    vert = np.c_[inds[:-2, :].ravel(), inds[2:, :].ravel()] 
    #    #all rows, not first col, make to 1d
    #    edges2 = np.vstack([horz, vert]).astype(np.int32) 
    #    #horz is first element, vert is 
    #    theweights2 = np.ones((np.shape(edges2))).astype(np.int32)
    #    edges2 = np.hstack((edges2,theweights2))[:,0:3].astype(np.int32)
    #
    #    edges = np.vstack([edges,edges2]).astype(np.int32)

        pairwise_cost = np.array([[0, 1], [1, 0]], dtype = np.int32)
    
        energies = np.dstack((np.array(source_slice).astype(np.int32).flatten(), \
        np.array(sink_slice).astype(np.int32).flatten())).squeeze()

        segmented_slice = cut_from_graph(edges, energies, pairwise_cost, 3, \
          'expansion') 
        segmented_image[:,:,slice_num] = segmented_slice.reshape(length,width)

    return segmented_image

def compute_distance_to_atlas(atlas):
    """Computes the Eucledian distance to a thresholded probabilistic atlas   
     
    Parameters
    ----------
    atlas: A float array with shape (L, M, N) 
            representing the probabilistic atlas 
        ...
        
    Returns
    -------
    atlas_distance_map : A float array with shape (L, M, N) 
        Contains distances to the thresholded atlas
    """
    
    leftLungPriorthres = np.ones((np.shape(atlas)), dtype=float) 
    leftLungPriorthres[atlas < 0.5] = 1.0    
    leftLungPriorthres[atlas >= 0.5] = 0.0      
    atlas_distance_map = \
        ndimage.morphology.distance_transform_edt(leftLungPriorthres)
               
    return atlas_distance_map


def compute_gauss_intensities_exp_distance_likelihood(intensity_data, distance_data, x, d0x):
    """
    computes a  an exponential distribution in distance and a gaussian \
    distribution in intensities with means and variances linearly depending
    on distance
    """
    imshape = np.shape(intensity_data)
    intensity_vec = np.ravel(intensity_data).astype(np.float)
    distance_vec = np.ravel(distance_data).astype(np.float)
    
    #if (x[6]==-1):
    #    mask=distance_vec<-1
    #else:
    #    mask = distance_vec < 0.2
    
    mask=distance_vec<-1

    myfun2 = np.zeros_like(intensity_vec)
    
    numerator = np.exp(-(pow((intensity_vec[~mask]- (x[0]*distance_vec[~mask]+x[1])),2)/\
          (2*pow((x[2]*distance_vec[~mask]+x[3]),2)) + x[4]*distance_vec[~mask])  )
    denom = (x[2]+x[3]*x[4])*np.sqrt(2*np.pi)/(x[4])*(x[4])
    myfun2[~mask] = numerator/denom
        
    myfun3 = np.reshape(myfun2, (imshape[0],imshape[1],imshape[2]))
    return myfun3
    
def compute_non_pec_likelihood(intensity_data, distance_data, xclassifier):    
    imshape = np.shape(intensity_data)
    intensity_vec = np.ravel(intensity_data).astype(np.float)
    distance_vec = np.ravel(distance_data).astype(np.float)
    
    ivec = np.ones([np.shape(intensity_vec)[0], 2]).astype('double') 
    ivec[:,0] = intensity_vec
    ivec[:,1] = distance_vec
        
    myfun2 = np.exp(xclassifier.eval(ivec)[0])
    myfun3 = np.reshape(myfun2, (imshape[0],imshape[1],imshape[2]))
    
    return myfun3
                
def compute_variable_mean_gaussian(intensity_data, distance_data, x):
    
    imshape = np.shape(intensity_data)
    intensity_vec = np.ravel(intensity_data).astype(np.float)
    distance_vec = np.ravel(distance_data).astype(np.float)
    
    #if (x[6]==-1):
    #    mask=distance_vec<-1
    #else:
    #    mask = distance_vec < 0.2
    #mask=distance_vec<-1

    myfun2 = np.zeros_like(intensity_vec)
    
    #case for distance >0i
    #pow1 = pow((intensity_vec - (x[0]*distance_vec+x[1])),2)
    numerator = np.exp(-(pow((intensity_vec- (x[0]*distance_vec+x[1])),2)/\
          (2*pow((x[2]*distance_vec+x[3]),2)))  )
          
    numerator2= np.exp(-pow(distance_vec- x[4],2)/(2*pow(x[5],2)))
    denom = ((x[3]+x[2]*x[4])*2*np.pi*x[5])
    

    myfun2 = (numerator*numerator2)/denom
    
    ##case for distance = 0
    #if x[6]>=0:
        #myfun2[mask] = stats.norm.pdf(intensity_vec[mask], loc=x[5], scale=x[6])
    #d0voxels = (distance_data < 0.002 )
    #print(np.shape(gausFun))
    #print(np.shape(myfun2))
    #myfun2[(distance_vec < 0.002  )] = gausFun[(distance_vec < 0.002 )]  
    #
    #case for intensities larger than threshold
    #intensity_threshold = ((intensity_vec >= 90)  | (distance_vec <= -50))
    #print(np.shape(intensity_threshold))
    #zerolikelihood = np.ones_like(myfun2)*0.0000000000000000000000001
    #myfun2[intensity_threshold] = zerolikelihood[intensity_threshold]
    
    myfun3 = np.reshape(myfun2, (imshape[0],imshape[1],imshape[2]))
    return myfun3
    
def norm_pdf_multivariate(x, mu, sigma):
  #print(np.shape(x)) 
  #print(np.shape(mu))  
  #print(np.shape(sigma))  
  #
  #print(type(x)) 
  #print(type(mu))  
  #print(type(sigma))  
  #
  #print(mu)
  
  size = len(x)
  if size == len(mu) and (size, size) == sigma.shape:
    det = np.linalg.det(sigma)
    if det == 0:
        raise NameError("The covariance matrix can't be singular")

    norm_const = 1.0/ ( math.pow((2*np.pi),float(size)/2) * math.pow(det,1.0/2) )
#
    result = np.zeros((np.shape(x)[1])).astype(float)
    for i in range(0, np.shape(x)[1]-1):
        x_mu = np.matrix(x[:,i] - mu)
        inv = np.linalg.inv(sigma)        
        result[i] = math.pow(math.e, -0.5 * (x_mu * inv * x_mu.T)) *norm_const
    return result
