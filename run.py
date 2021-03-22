import numpy as np
import logging
import shutil
import json
import sys
import os

import cytomine
from cytomine.models import AnnotationCollection, Job
from cytomine.models.software import JobCollection, JobParameterCollection, JobDataCollection, JobData

__version__ = "1.0.8"


def get_stats_annotations(params):

    annotations = AnnotationCollection()

    annotations.project = params.cytomine_id_project
    annotations.term = params.terms_to_analyze

    if type(params.terms_to_analyze) != "NoneType":
        annotations.term = params.terms_to_analyze

    if type(params.images_to_analyze) != "NoneType":
        annotations.image = params.images_to_analyze

    annotations.showWKT = True
    annotations.showMeta = True
    annotations.showGIS = True
    annotations.showTerm = True
    annotations.fetch()

    filtered_by_id = [annotation for annotation in annotations if (params.cytomine_id_annotation == annotation.id)]

    if (type(params.cytomine_id_annotation) != "NoneType") and (len(filtered_by_id)>0):
        return filtered_by_id
    else:
        return annotations

def get_results(params):

    results = []
    equiv, equiv2 = {}, {}

    jobs = JobCollection()
    jobs.project = params.cytomine_id_project
    jobs.fetch()
    jobs_ids = [job.id for job in jobs]

    for job_id in jobs_ids:

        jobparamscol = JobParameterCollection().fetch_with_filter(key="job", value=job_id)
        jobdatacol = JobDataCollection().fetch_with_filter(key="job", value=job_id)

        for job in jobdatacol:

            jobdata = JobData().fetch(job.id)
            filename = jobdata.filename

            for param in jobparamscol:
                if str(param).split(" : ")[1] in ["cytomine_image"]:
                    equiv.update({filename:int(param.value)})
                if str(param).split(" : ")[1] in ["cytomine_id_term"]:
                    equiv2.update({filename:param.value})

            if "detections" in filename:
                try:
                    jobdata.download(os.path.join("tmp/", filename))
                except AttributeError:
                    continue

    temp_files = os.listdir("tmp")
    for i in range(0, len(temp_files)):
        if temp_files[i][-4:] == "json":
            filename = temp_files[i]
            try:
                image = equiv[filename]
                terms = equiv2[filename]
                with open("tmp/"+filename, 'r') as json_file:
                    data = json.load(json_file)
                    json_file.close()
                results.append({"image":image, "terms":terms ,"data":data})
            except KeyError:
                continue

    os.system("cd tmp&&rm detections*")

    return results

def process_polygon(polygon):
    pol = str(polygon)[len("MULTIPOINT "):].rstrip("(").lstrip(")").split(",")
    for i in range(0, len(pol)):
        pol[i] = pol[i].rstrip(" ").lstrip(" ")
        pol[i] = pol[i].rstrip(")").lstrip("(").split(" ")
    return pol

def process_points(points):
    pts = [[p["x"],p["y"]] for p in points]
    return pts

def is_inside(point, polygon):

    print(point)
    print(polygon)

    v_list = []
    for vert in polygon:
        vector = [0,0]
        vector[0] = float(vert[0]) - float(point[0])
        vector[1] = float(vert[1]) - float(point[1])
        v_list.append(vector)

    v_list.append(v_list[0])

    angle = 0
    for i in range(0, len(v_list)-1):
        v1 = v_list[i]
        v2 = v_list[i+1]
        unit_v1 = v1 / np.linalg.norm(v1)
        unit_v2 = v2 / np.linalg.norm(v2)
        dot_prod = np.dot(unit_v1, unit_v2)
        angle += np.arccos(dot_prod)

    if round(angle, 4) == 6.2832:
        return True
    else:
        return False

def get_stats(annotations, results):

    stats = {}
    inside_points_l = []

    for annotation in annotations:
        annotation_dict, inside_points = {}, {}
        polygon = process_polygon(annotation.location)

        for result in results:
            if result["image"] == annotation.image:

                points = result["data"]
                image_info, global_cter = {}, 0
                for key, value in points.items():
                    count = len(value)
                    global_cter+=count
                    image_info.update({"conteo_{}_imagen".format(key):count})

                image_info.update({"conteo_total_imagen":global_cter})
                image_info.update({"area_anotacion":annotation.area})
                annotation_dict.update({"info_imagen":image_info})

                for key, value in points.items():
                    ins_p = []
                    pts = process_points(value)
                    cter = 0
                    for p in pts:
                        if is_inside(p, polygon):
                            ins_p.append({"x":p[0], "y":p[1]})
                            cter+=1
                    inside_points.update({key:ins_p})
                    particular_info ={
                        "conteo_{}_anotacion".format(key):cter,
                        "densidad_{}_anotación(n/micron²)".format(key):cter/annotation.area
                    }
                    annotation_dict.update({"info_termino_{}".format(key):particular_info})
        inside_points_l.append([annotation.id, inside_points, result["terms"]])
        stats.update({annotation.id:annotation_dict})

    return stats, inside_points_l

def run(cyto_job, parameters):

    logging.info("----- test software v%s -----", __version__)
    logging.info("Entering run(cyto_job=%s, parameters=%s)", cyto_job, parameters)

    job = cyto_job.job
    project = cyto_job.project

    working_path = os.path.join("tmp", str(job.id))
    if not os.path.exists(working_path):
        logging.info("Creating working directory: %s", working_path)
        os.makedirs(working_path)

    try:

        job.update(progress=0, statusComment="Recogiendo anotaciones Stats")
        anotaciones = get_stats_annotations(parameters)
        
        if len(anotaciones) == 0:
            job.update(progress=100, status=Job.FAILED, statusComment="No se han podido encontrar anotaciones stats!")

        job.update(progress=15, statusComment="Recogiendo resultados")
        resultados = get_results(parameters)

        if len(resultados) == 0:
            job.update(progress=100, status=Job.FAILED, statusComment="No se han podido encontrar resultados para las anotaciones dadas!")

        job.update(progress=30, statusComment="Calculando estadísticas")
        stats, inside_points_l = get_stats(anotaciones, resultados)

        if len(stats) == 0:
            job.update(progress=100, status=Job.FAILED, statusComment="No se han podido calcular las estadísticas!")

    finally:
        logging.info("Deleting folder %s", working_path)
        shutil.rmtree(working_path, ignore_errors=True)
        logging.debug("Leaving run()")

if __name__ == '__main__':

    logging.debug("Command: %s", sys.argv)

    with cytomine.CytomineJob.from_cli(sys.argv) as cyto_job:

        run(cyto_job, cyto_job.parameters)