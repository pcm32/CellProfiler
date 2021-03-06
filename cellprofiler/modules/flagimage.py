'''<b>Flag Image</b> allows you to flag an image based on properties 
that you specify, for example, quality control measurements.
<hr>

This module allows you to assign a flag if
an image meets certain measurement criteria that you specify (for 
example, if the image fails a quality control measurement).  The
value of the flag is 1 if the image meets the selected criteria (for 
example, if it fails QC), and 0 if it does not meet the criteria (if 
it passes QC). The flag can be used in post-processing to filter out 
images you do not want to analyze, e.g., in CellProfiler Analyst. In 
addition, you can use <b>ExportToSpreadsheet</b> to generate a file 
that includes the flag as a metadata measurement associated with the 
images. The <b>Metadata</b> module can then use this flag 
to put images that pass QC into one group and images that fail 
into another.

A flag can be based on one or more measurements. If you create a flag 
based on more than one measurement, you can choose between setting the
flag if all measurements are outside the bounds or if one of the 
measurements is outside of the bounds.

This module must be placed in the pipeline after the relevant measurement 
modules upon which the flags are based.
'''

# CellProfiler is distributed under the GNU General Public License.
# See the accompanying file LICENSE for details.
# 
# Copyright (c) 2003-2009 Massachusetts Institute of Technology
# Copyright (c) 2009-2014 Broad Institute
# 
# Please see the AUTHORS file for credits.
# 
# Website: http://www.cellprofiler.org


import logging
import numpy as np
import sys
import os

import cellprofiler.cpmodule as cpm
import cellprofiler.measurements as cpmeas
import cellprofiler.settings as cps
from cellprofiler.settings import YES, NO
import cellprofiler.workspace as cpw
from cellprofiler.gui.help import USING_METADATA_TAGS_REF, USING_METADATA_HELP_REF
import cellprofiler.utilities.rules as cprules
from cellprofiler.preferences import IO_FOLDER_CHOICE_HELP_TEXT

logger = logging.getLogger(__name__)
C_ANY = "Flag if any fail"
C_ALL = "Flag if all fail"

S_IMAGE = "Whole-image measurement"
S_AVERAGE_OBJECT = "Average measurement for all objects in each image"
S_ALL_OBJECTS = "Measurements for all objects in each image"
S_RULES = "Rules"
S_ALL = [S_IMAGE, S_AVERAGE_OBJECT, S_ALL_OBJECTS, S_RULES]

'''Number of settings in the module, aside from those in the flags'''
N_FIXED_SETTINGS = 1

'''Number of settings in each flag, aside from those in the measurements'''
N_FIXED_SETTINGS_PER_FLAG = 5

N_SETTINGS_PER_MEASUREMENT_V2 = 7
N_SETTINGS_PER_MEASUREMENT_V3 = 9
'''Number of settings per measurement'''
N_SETTINGS_PER_MEASUREMENT = 10

class FlagImage(cpm.CPModule):
   
    category = "Data Tools"
    variable_revision_number = 4
    module_name = "FlagImage"
    
    def create_settings(self):
        self.flags = []
        self.flag_count = cps.HiddenCount(self.flags)
        self.add_flag_button = cps.DoSomething("", "Add another flag",
                                               self.add_flag)
        self.spacer_1 = cps.Divider()
        self.add_flag(can_delete = False)
        
    def add_flag(self, can_delete=True):
        group = cps.SettingsGroup()
        group.append("divider1", cps.Divider(line=False))
        group.append("measurement_settings", [])
        group.append("measurement_count", cps.HiddenCount(group.measurement_settings))
        group.append("category", 
                     cps.Text(
                        "Name the flag's category","Metadata", doc = '''
                        Name a measurement category by which to categorize the flag. The <i>Metadata</i> 
                        category is the default used in CellProfiler to store information about 
                        images (referred to as <i>metadata</i>).</p>
                        <p>The flag is stored as a per-image measurement whose name is a combination of the
                        flag's category and feature name, underscore delimited. 
                        For instance, if the measurement category is
                        <i>Metadata</i> and the feature name is <i>QCFlag</i>, then the default
                        measurement name would be <i>Metadata_QCFlag</i>. %s</p>'''%USING_METADATA_HELP_REF))
        
        group.append("feature_name", 
                     cps.Text(
                        "Name the flag","QCFlag", doc = '''
                        The flag is stored as a per-image measurement whose name is a combination of the
                        flag's category and feature name, separated by underscores. 
                        For instance, if the measurement category is
                        <i>Metadata</i> and the feature name is <i>QCFlag</i>, then the default
                        measurement name would be <i>Metadata_QCFlag</i>.'''))
        
        group.append("combination_choice", 
                     cps.Choice(
                        "Flag if any, or all, measurement(s) fails to meet the criteria?",
                        [ C_ANY, C_ALL], doc = '''
                        <ul>
                        <li><i>%(C_ANY)s:</i> An image will be flagged if any of its measurements fail. This can be useful
                        for flagging images possessing multiple QC flaws; for example, you can flag all bright images 
                        and all out of focus images with one flag.</li>
                        <li><i>%(C_ALL)s:</i> A flag will only be assigned if all measurements fail.  This can be useful 
                        for flagging images that possess only a combination
                        of QC flaws; for example, you can flag only images that are both bright and out of focus.</li>
                        </ul>'''%globals()))
        
        group.append("wants_skip", 
                     cps.Binary(
                        "Skip image set if flagged?", False, doc = """
                        <p>Select <i>%(YES)s</i> to skip the remainder of the pipeline for image sets
                        that are flagged. CellProfiler will not run subsequent modules in the
                        pipeline on the images in any image set that is flagged. 
                        Select <i>%(NO)s</i> for CellProfiler to continue to process the pipeline regardless
                        of flagging.</p>
                        <p>You may want to skip processing in order to filter out
                        unwanted images. For instance, you may want
                        to exclude out of focus images when running 
                        <b>CorrectIllumination_Calculate</b>. You can do this with a
                        pipeline that measures image quality and flags inappropriate
                        images before it runs <b>CorrectIllumination_Calculate</b>.</p>"""%globals()))
            
        group.append("add_measurement_button", 
                     cps.DoSomething("",
                                     "Add another measurement",
                                     self.add_measurement, group))
        self.add_measurement(group, False if not can_delete else True)
        if can_delete:
            group.append("remover", cps.RemoveSettingButton("", "Remove this flag", self.flags, group))
        group.append("divider2", cps.Divider(line=True))
        self.flags.append(group)

    def add_measurement(self, flag_settings, can_delete=True):
        measurement_settings = flag_settings.measurement_settings

        group = cps.SettingsGroup()
        group.append("divider1", cps.Divider(line=False))
        group.append("source_choice",
                     cps.Choice(
                        "Flag is based on", S_ALL, doc = '''
                        <ul>
                        <li><i>%(S_IMAGE)s:</i> A per-image measurement, such as intensity or 
                        granularity.</li>
                        <li><i>%(S_AVERAGE_OBJECT)s:</i> The average of all 
                        object measurements in the image.</li>
                        <li><i>%(S_ALL_OBJECTS)s:</i> All the 
                        object measurements in an image, without averaging. In other words, if <i>any</i> 
                        of the objects meet the criteria, the image will be flagged.</li>
                        <li><i>%(S_RULES)s:</i>Use a text file of rules produced by CellProfiler Analyst. If you 
                        choose <i>Rules</i>, you will have to ensure that this pipeline makes every measurement 
                        in the rules file prior to this module.</li>
                        </ul>'''%globals()))
        
        group.append("object_name",
                     cps.ObjectNameSubscriber(
                        "Select the object to be used for flagging",
                        cps.NONE, doc = '''
                        <i>(Used only when flag is based on an object measurement)</i><br>
                        Select the objects whose measurements you want to use for flagging.'''))

        def object_fn():
            if group.source_choice == S_IMAGE:
                return cpmeas.IMAGE
            return group.object_name.value

        group.append("rules_directory",
                     cps.DirectoryPath(
                        "Rules file location",doc = """
                        <i>(Used only when flagging using %(S_RULES)s)</i><br>
                        Select the location of the rules file that will be used for filtering.
                        %(IO_FOLDER_CHOICE_HELP_TEXT)s""" % globals()))
         
        def get_directory_fn():
            '''Get the directory for the rules file name'''
            return group.rules_directory.get_absolute_path()
                
        def set_directory_fn(path):
            dir_choice, custom_path = group.rules_directory.get_parts_from_path(path)
            group.rules_directory.join_parts(dir_choice, custom_path)
        
        group.append("rules_file_name", 
                     cps.FilenameText(
                        "Rules file name","rules.txt",
                        get_directory_fn = get_directory_fn,
                        set_directory_fn = set_directory_fn,doc="""
                        <i>(Used only when flagging using %(S_RULES)s)</i><br>
                        The name of the rules file. This file should be a plain text
                        file containing the complete set of rules.
                        <p>Each line of
                        this file should be a rule naming a measurement to be made
                        on an image, for instance:
                        <pre>IF (Image_ImageQuality_PowerLogLogSlope_DNA &lt; -2.5, [0.79, -0.79], [-0.94, 0.94])</pre><br><br>
                        The above rule will score +0.79 for the positive category and -0.94
                        for the negative category for images whose power log slope is less than -2.5
                        pixels and will score the opposite for images whose slope is larger.
                        The filter adds positive and negative and flags the images whose
                        positive score is higher than the negative score.</p>"""%globals()))
        
        def get_rules_class_choices(group=group):
            '''Get the available choices from the rules file'''
            try:
                rules = self.get_rules(group)
                nclasses = len(rules.rules[0].weights[0])
                return [str(i) for i in range(1, nclasses+1)]
            except:
                return [str(i) for i in range(1, 3)]
        
        group.append("rules_class", 
                     cps.MultiChoice(
                        "Class number",
                        choices = ["1", "2"],doc = """
                        <i>(Used only when flagging using %(S_RULES)s)</i><br>
                        Select which classes to flag when filtering. The
                        CellProfiler Analyst classifier user interface lists the names of 
                        the classes in order. By default, these are the positive (class 1)
                        and negative (class 2) classes. <b>FlagImage</b> uses the
                        first class from CellProfiler Analyst if you choose "1", etc. 
                        <p>Please note the following:
                        <ul>
                        <li>The flag is set if the image falls into the selected class.</li>
                        <li>You can make multiple class selections. If you do so, the module
                        will set the flag if the image falls into any of the selected classes.</li>
                        </ul></p>"""%globals()))
        
        group.rules_class.get_choices = get_rules_class_choices

        group.append("measurement", 
                     cps.Measurement("Which measurement?",object_fn))
        
        group.append("wants_minimum",
                     cps.Binary(
                         "Flag images based on low values?",True, doc = '''
                         Select <i>%(YES)s</i> to flag images with measurements below the specified cutoff.'''%globals()))
        
        group.append("minimum_value", cps.Float("Minimum value", 0))
        
        group.append("wants_maximum",
                     cps.Binary(
                         "Flag images based on high values?",True, doc = '''
                         Select <i>%(YES)s</i> to flag images with measurements above the specified cutoff.'''%globals()))
        
        group.append("maximum_value", cps.Float("Maximum value", 1))
        
        if can_delete:
            group.append("remover", cps.RemoveSettingButton("", "Remove this measurement", measurement_settings, group))
            
        group.append("divider2", cps.Divider(line=True))
        measurement_settings.append(group)

    
    def settings(self):
        result = [self.flag_count]
        for flag in self.flags:
            result += [flag.measurement_count, flag.category, flag.feature_name, 
                       flag.combination_choice, flag.wants_skip]
            for mg in flag.measurement_settings:
                result += [mg.source_choice, mg.object_name, mg.measurement,
                           mg.wants_minimum, mg.minimum_value,
                           mg.wants_maximum, mg.maximum_value, 
                           mg.rules_directory, mg.rules_file_name,
                           mg.rules_class]
        return result
    
    def prepare_settings(self, setting_values):
        '''Construct the correct number of flags'''
        flag_count = int(setting_values[0])
        del self.flags[:]
        self.add_flag(can_delete=False)
        while len(self.flags) < flag_count:
            self.add_flag()
            
        setting_values = setting_values[N_FIXED_SETTINGS:]
        for flag in self.flags:
            count = int(setting_values[0])
            # Adding a flag adds the first measurement automatically
            while len(flag.measurement_settings) < count:
                self.add_measurement(flag, can_delete=True)
            setting_values = setting_values[N_FIXED_SETTINGS_PER_FLAG +
                                            count * N_SETTINGS_PER_MEASUREMENT:]
    
    def visible_settings(self):
        def measurement_visibles(m_g):
            if hasattr(m_g, "remover"):
                result = [cps.Divider(line=True)]
            else:
                result = []
            result += [m_g.source_choice]
            
            if m_g.source_choice == S_ALL_OBJECTS or m_g.source_choice == S_AVERAGE_OBJECT:
                result += [m_g.object_name]
            if m_g.source_choice == S_RULES:
                result += [m_g.rules_directory, m_g.rules_file_name,
                           m_g.rules_class]
            else:
                result += [m_g.measurement, m_g.wants_minimum]
                if m_g.wants_minimum.value:
                    result += [m_g.minimum_value]
                result += [m_g.wants_maximum]
                if m_g.wants_maximum.value:
                    result += [m_g.maximum_value]
            if hasattr(m_g, "remover"):
                result += [m_g.remover, cps.Divider(line=True)]
            return result

        def flag_visibles(flag):
            if hasattr(flag, "remover"):
                result = [cps.Divider(line=True),cps.Divider(line=True)]
            else:
                result = []
            result += [flag.category, flag.feature_name, flag.wants_skip]
            if len(flag.measurement_settings) > 1:
                result += [flag.combination_choice]
            for measurement_settings in flag.measurement_settings:
                result += measurement_visibles(measurement_settings)
            result += [flag.add_measurement_button]
            if hasattr(flag, "remover"):
                result += [flag.remover, cps.Divider(line=True),cps.Divider(line=True)]
            return result

        result = []
        for flag in self.flags:
            result += flag_visibles(flag)

        result += [self.add_flag_button]
        return result

    def validate_module(self, pipeline):
        '''If using rules, validate them'''
        for flag in self.flags:
            for measurement_setting in flag.measurement_settings:
                if measurement_setting.source_choice == S_RULES:
                    try:
                        rules = self.get_rules(measurement_setting)
                    except Exception, instance:
                        logger.warning("Failed to load rules: %s", str(instance), exc_info=True)
                        raise cps.ValidationError(str(instance),
                                                  measurement_setting.rules_file_name)
                    if not np.all([r.object_name == cpmeas.IMAGE for r in rules.rules]):
                        raise cps.ValidationError("The rules listed in %s describe objects instead of images."%measurement_setting.rules_file_name.value,
                                                    measurement_setting.rules_file_name)
                    rule_features = [r.feature for r in rules.rules]
                    measurement_cols = [c[1] for c in pipeline.get_measurement_columns(self)]
                    undef_features = list(set(rule_features).difference(measurement_cols))
                    if len(undef_features) > 0:
                        raise cps.ValidationError("The rule described by %s has not been measured earlier in the pipeline."%undef_features[0],
                                                    measurement_setting.rules_file_name)

    def run(self, workspace):
        col_labels = ("Flag", "Source", "Measurement", "Value","Pass/Fail")
        statistics = []
        for flag in self.flags:
            statistics += self.run_flag(workspace, flag)
        if self.show_window:
            workspace.display_data.statistics = statistics
            workspace.display_data.col_labels = col_labels
        
    def display(self, workspace, figure):
        figure.set_subplots((1, 1))
        figure.subplot_table(0, 0, workspace.display_data.statistics,
                             col_labels = workspace.display_data.col_labels)

    def run_as_data_tool(self, workspace):
        m = workspace.measurements
        assert isinstance(m, cpmeas.Measurements)
        m.is_first_image = True
        image_set_count = m.image_set_count
        for i in range(image_set_count):
            self.run(workspace)
            img_stats = workspace.display_data.statistics
            if i == 0:
                header = ["Image set"]
                for flag_name, object_name, feature, value, pf in img_stats:
                    header.append(flag_name)
                header.append("Pass/Fail")
                statistics = [header]
            row = [str(i+1)]
            ok = True
            for flag_name, object_name, feature, value, pf in img_stats:
                ok = ok and (pf == "Pass")
                row.append(str(value))
            row.append("Pass" if ok else "Fail")
            statistics.append(row)
            if i < image_set_count - 1:
                m.next_image_set()
        self.show_window = False
        if image_set_count > 0:
            import wx
            from wx.grid import Grid, PyGridTableBase, EVT_GRID_LABEL_LEFT_CLICK
            from cellprofiler.gui import get_cp_icon
            
            frame = wx.Frame(workspace.frame, -1, "Flag image results")
            sizer = wx.BoxSizer(wx.VERTICAL)
            frame.SetSizer(sizer)
            grid = Grid(frame, -1)
            sizer.Add(grid, 1, wx.EXPAND)
            #
            # The flag table supplies the statistics to the grid
            # using the grid table interface
            #
            sort_order = np.arange(len(statistics)-1)
            sort_col = [None]
            sort_ascending = [None]
            def on_label_clicked(event):
                col = event.GetCol()
                if sort_col[0] == col:
                    sort_ascending[0] = not sort_ascending[0]
                else:
                    sort_ascending[0] = True
                sort_col[0] = col
                data = [x[col] for x in statistics[1:]]
                try:
                    data = np.array(data,float)
                except ValueError:
                    data = np.array(data)
                if sort_ascending[0]:
                    sort_order[:] = np.lexsort((data,))
                else:
                    sort_order[::-1] = np.lexsort((data,))
                grid.ForceRefresh()
                
            grid.Bind(EVT_GRID_LABEL_LEFT_CLICK, on_label_clicked)
            
            class FlagTable(PyGridTableBase):
                def __init__(self):
                    PyGridTableBase.__init__(self)
                def GetColLabelValue(self, col):
                    if col == sort_col[0]:
                        if sort_ascending[0]:
                            
                            return statistics[0][col]+" v"
                        else:
                            return statistics[0][col]+" ^"
                    return statistics[0][col]
                def GetNumberRows(self):
                    return len(statistics)-1
                def GetNumberCols(self):
                    return len(statistics[0])
                def GetValue(self, row, col):
                    return statistics[sort_order[row]+1][col]
            grid.SetTable(FlagTable())
            frame.Fit()
            max_size = int(wx.SystemSettings.GetMetric(wx.SYS_SCREEN_Y) * 3 / 4)
            if frame.Size[1] > max_size:
                frame.SetSize((frame.Size[0], max_size))
            frame.SetIcon(get_cp_icon())
            frame.Show()
            
        
    def measurement_name(self, flag):
        return "_".join((flag.category.value, flag.feature_name.value))

    def get_rules(self, measurement_group):
        '''Read the rules from a file'''
        rules_file = measurement_group.rules_file_name.value
        rules_directory = measurement_group.rules_directory.get_absolute_path()
        path = os.path.join(rules_directory, rules_file)
        if not os.path.isfile(path):
            raise cps.ValidationError("No such rules file: %s"%path, rules_file)
        else:
            rules = cprules.Rules()
            rules.parse(path)
            return rules

    def run_flag(self, workspace, flag):
        ok, stats = self.eval_measurement(workspace, 
                                          flag.measurement_settings[0])
        statistics = [tuple([self.measurement_name(flag)] + list(stats))]
        for measurement_setting in flag.measurement_settings[1:]:
            ok_1, stats = self.eval_measurement(workspace, measurement_setting)
            statistics += [tuple([self.measurement_name(flag)] + list(stats))]
            if flag.combination_choice == C_ALL:
                ok = ok or ok_1
            elif flag.combination_choice == C_ANY:
                ok = ok and ok_1
            else:
                raise NotImplementedError("Unimplemented combination choice: %s" %
                                          flag.combination_choice.value)
        m = workspace.measurements
        assert isinstance(m, cpmeas.Measurements)
        m.add_image_measurement(self.measurement_name(flag), 0 if ok else 1)
        if (not ok) and flag.wants_skip:
            workspace.disposition = cpw.DISPOSITION_SKIP
        return statistics
        
    def eval_measurement(self, workspace, ms):
        '''Evaluate a measurement
        
        workspace - holds the measurements to be evaluated
        ms - the measurement settings indicating how to evaluate
        
        returns a tuple
           first tuple element is True = pass, False = Fail
           second tuple element has all of the statistics except for the
                        flag name
        '''
        m = workspace.measurements
        assert isinstance(m, cpmeas.Measurements)
        fail = False
        if ms.source_choice == S_IMAGE:
            value = m.get_current_image_measurement(ms.measurement.value)
            min_value = max_value = value
            display_value = str(round(value,3))
            source = cpmeas.IMAGE
        elif ms.source_choice == S_AVERAGE_OBJECT:
            data = m.get_current_measurement(ms.object_name.value,
                                             ms.measurement.value)
            if len(data) == 0:
                min_value = max_value = np.NaN
                fail = True
                display_value = "No objects"
            else:
                min_value = max_value = np.mean(data)
                display_value = str(round(min_value, 3))
            source = "Ave. %s"%ms.object_name.value
        elif ms.source_choice == S_ALL_OBJECTS:
            data = m.get_current_measurement(ms.object_name.value,
                                             ms.measurement.value)
            source = ms.object_name.value
            if len(data) == 0:
                min_value = max_value = np.NaN
                fail = True
                display_value = "No objects"
            else:
                min_value = np.min(data)
                max_value = np.max(data)
                if min_value == max_value:
                    display_value = str(min_value)
                else:
                    display_value = "%.3f - %.3f"%(min_value,max_value)
        elif ms.source_choice == S_RULES:
            rules = self.get_rules(ms)
            scores = rules.score(workspace.measurements)
            rules_classes = np.array(
                [int(x)-1 for x in ms.rules_class.get_selections()])
            #
            # There should only be one in the vector, but if not, take
            # a majority vote (e.g. are there more class 1 objects than
            # class 2?)
            #
            is_not_nan = np.any(~ np.isnan(scores), 1)
            objclass = np.argmax(scores[is_not_nan, :], 1).flatten()
            hit_count = np.sum(
                objclass[:, np.newaxis] == rules_classes[np.newaxis, :])
            fail = hit_count > scores.shape[0] - hit_count
            source = cpmeas.IMAGE
            if len(scores) > 1:
                display_value = "%d of %d" % (hit_count, scores.shape[0])
            else:
                display_value = "--"
        else:
            raise NotImplementedError("Source choice of %s not implemented" %
                                      ms.source_choice)
        fail = ((ms.source_choice != S_RULES and (fail or
                (ms.wants_minimum.value and 
                 min_value < ms.minimum_value.value) or
                (ms.wants_maximum.value and
                 max_value > ms.maximum_value.value))) or
                (ms.source_choice == S_RULES and fail))
        
        return ((not fail), (source, ms.measurement.value if ms.source_choice != S_RULES else "Rules", display_value, 
                             "Fail" if fail else "Pass"))
    
    def get_measurement_columns(self, pipeline):
        '''Return column definitions for each flag mesurment in the module'''
        return [(cpmeas.IMAGE, self.measurement_name(flag), cpmeas.COLTYPE_INTEGER)
                for flag in self.flags]
    
    def get_categories(self, pipeline, object_name):
        if object_name == cpmeas.IMAGE:
            return [flag.category.value for flag in self.flags]
        return []
    
    def get_measurements(self, pipeline, object_name, category):
        if object_name != cpmeas.IMAGE:
            return []
        return [flag.feature_name.value for flag in self.flags
                if flag.category.value == category]

    def upgrade_settings(self, setting_values, variable_revision_number,
                         module_name, from_matlab):
        if from_matlab and (variable_revision_number == 1 or variable_revision_number == 2):
            
            if variable_revision_number == 1:
                image_name, category, feature_num_or_name, min_value, max_value, \
                      new_or_append, new_name, old_name = setting_values
                measurement_name = '_'.join((category, feature_num_or_name,
                                             image_name))
            elif variable_revision_number == 2:
                image_name, category, feature_num_or_name, scale, min_value, max_value, \
                      new_or_append, new_name, old_name = setting_values
                 
                measurement_name = '_'.join((category, feature_num_or_name,
                                             image_name, scale))
            if min_value == 'No minimum':
                wants_minimum = cps.NO
                min_value = "0"
            else:
                wants_minimum = cps.YES
            if max_value == 'No maximum':
                wants_maximum = cps.NO
                max_value = "1"
            else:
                wants_maximum = cps.YES
            if new_or_append == "Append existing flag":
                logger.warning("CellProfiler 2.0 can't combine flags from multiple FlagImageForQC modules imported from version 1.0")
            
            new_name_split = new_name.find('_')
            if new_name_split == -1:
                flag_category = 'Metadata'
                flag_feature = new_name
            else:
                flag_category = new_name[:new_name_split]
                flag_feature = new_name[new_name_split+1:]
            setting_values = ["1", # of flags in module
                              "1", # of measurements in the flag
                              flag_category,
                              flag_feature,
                              C_ANY, # combination choice
                              S_IMAGE, # measurement source
                              cps.NONE, # object name
                              measurement_name,
                              wants_minimum,
                              min_value,
                              wants_maximum,
                              max_value]
            from_matlab = False
            variable_revision_number = 1
            
        if (not from_matlab) and variable_revision_number == 1:
            new_setting_values = [setting_values[0]]
            idx = 1
            for flag_idx in range(int(setting_values[0])):
                new_setting_values += setting_values[idx:idx+4] + [cps.NO]
                meas_count = int(setting_values[idx])
                idx += 4
                for meas_idx in range(meas_count):
                    measurement_source = setting_values[idx]
                    if (measurement_source.startswith("Measurement for all") or
                        measurement_source == "All objects"):
                        measurement_source = S_ALL_OBJECTS
                    elif measurement_source=="Average for objects":
                        measurement_source = S_AVERAGE_OBJECT
                    elif measurement_source=="Image":
                        measurement_source = S_IMAGE
                    new_setting_values += [measurement_source] 
                    new_setting_values += setting_values[(idx+1):(idx+7)]
                    idx += 7
            setting_values = new_setting_values
            variable_revision_number = 2
        
        if (not from_matlab) and variable_revision_number == 2:
            # Added rules
            new_setting_values = [setting_values[0]]
            idx = 1
            for flag_idx in range(int(setting_values[0])):
                new_setting_values += setting_values[idx:idx+N_FIXED_SETTINGS_PER_FLAG]
                meas_count = int(setting_values[idx])
                idx += N_FIXED_SETTINGS_PER_FLAG
                for meas_idx in range(meas_count):
                    measurement_source = setting_values[idx]
                    new_setting_values += [measurement_source]
                    new_setting_values += setting_values[(idx+1):(idx+N_SETTINGS_PER_MEASUREMENT_V2)] + \
                        [cps.DirectoryPath.static_join_string(cps.DEFAULT_INPUT_FOLDER_NAME,cps.NONE), "rules.txt"]
                    idx += N_SETTINGS_PER_MEASUREMENT_V2
            setting_values = new_setting_values
            
            variable_revision_number = 3
            
        if (not from_matlab) and variable_revision_number == 3:
            # Added rules_class
            new_setting_values = setting_values[:1]
            idx = 1
            for flag_idx in range(int(setting_values[0])):
                new_setting_values += \
                    setting_values[idx:(idx+N_FIXED_SETTINGS_PER_FLAG)]
                meas_count = int(setting_values[idx])
                idx += N_FIXED_SETTINGS_PER_FLAG
                for meas_idx in range(meas_count):
                    new_setting_values += \
                        setting_values[idx:(idx+N_SETTINGS_PER_MEASUREMENT_V3)]
                    new_setting_values += ["1"]
                    idx += N_SETTINGS_PER_MEASUREMENT_V3
            setting_values = new_setting_values
            variable_revision_number = 4
            
        return setting_values, variable_revision_number, from_matlab
    
