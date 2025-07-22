from airtest.core.cv import Template, ST, MATCHING_METHODS, InvalidMatchingMethodError
 
def _new_cv_match(self, screen, strategy=None):
    # in case image file not exist in current directory:
    ori_image = self._imread()
    image = self._resize_image(ori_image, screen, ST.RESIZE_METHOD)
    ret = None
    if strategy is None:
        strategy = ST.CVSTRATEGY
        
    for method in strategy:
        # get function definition and execute:
        func = MATCHING_METHODS.get(method, None)
        if func is None:
            raise InvalidMatchingMethodError("Undefined method in CVSTRATEGY: '%s', try 'kaze'/'brisk'/'akaze'/'orb'/'surf'/'sift'/'brief' instead." % method)
        else:
            if method in ["mstpl", "gmstpl"]:
                ret = self._try_match(func, ori_image, screen, threshold=self.threshold, rgb=self.rgb, record_pos=self.record_pos,
                                        resolution=self.resolution, scale_max=self.scale_max, scale_step=self.scale_step)
            else:
                ret = self._try_match(func, image, screen, threshold=self.threshold, rgb=self.rgb)
        if ret:
            break
    return ret

def apply_patch():
    Template._cv_match = _new_cv_match