# -*- coding: utf-8 -*-
import contextlib
import re
import argparse
import json

import pathlib as pathlib
import sys

import requests

NUTRISCORE_REGEX = re.compile(r"nutri[-\s]?score", re.IGNORECASE)
WEIGHT_MENTIONS = (
    "poids net:",
    "poids net égoutté:",
    "net weight:",
    "peso neto:",
    "peso liquido:",
    "netto gewicht:",
)

WEIGHT_MENTIONS_RE = re.compile('|'.join((re.escape(x)
                                          for x in WEIGHT_MENTIONS)),
                                re.IGNORECASE)

WEIGHT_VALUES_REGEX = re.compile(
    r"([0-9]+[,.]?[0-9]*)\s*(fl oz|dl|cl|mg|mL|lbs|oz|g|kg|L)(?![^\s])")

PACKAGER_CODE = {
    "fr_emb": re.compile(r"EMB ?(\d ?\d ?\d ?\d ?\d)([a-zA-Z]{1,2})?"),
    "fr": re.compile("FR [a-zA-Z0-9.\-\s]{2,}? (?:CE|EC)"),
}

RECYCLING_REGEX = {
    'recycling': [
        re.compile(r"recycle", re.IGNORECASE),
    ],
    'throw_away': [
        re.compile(r"(?:throw away)|(?:jeter)", re.IGNORECASE)
    ]
}

LABELS_REGEX = {
    'en:organic': [
        re.compile(r"ingr[ée]dients?\sbiologiques?", re.IGNORECASE),
        re.compile(r"agriculture ue/non ue biologique", re.IGNORECASE),
    ],
}

BEST_BEFORE_DATE_REGEX = {
    'en': re.compile(
        r'\d\d\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s\d{4})?',
        re.IGNORECASE),
    'fr': re.compile(
        r'\d\d\s(?:Jan|Fev|Mar|Avr|Mai|Juin|Juil|Aou|Sep|Oct|Nov|Dec)(?:\s\d{4})?',
        re.IGNORECASE),
    'full_digits': re.compile(r'\d{2}[./]\d{2}[./](?:\d{2}){1,2}'),
}

TEMPERATURE_REGEX_STR = r"[+-]?\s*\d+\s*°?C"
TEMPERATURE_REGEX = re.compile(r"(?P<value>[+-]?\s*\d+)\s*°?(?P<unit>C)",
                               re.IGNORECASE)

STORAGE_INSTRUCTIONS_REGEX = {
    'max': re.compile(
        r"[aà] conserver [àa] ({0}) maximum".format(TEMPERATURE_REGEX_STR),
        re.IGNORECASE),
    'between': re.compile(
        r"[aà] conserver entre ({0}) et ({0})".format(TEMPERATURE_REGEX_STR),
        re.IGNORECASE),
}


def get_barcode_from_path(path):
    path = pathlib.Path(path)

    barcode = ''

    for parent in path.parents:
        if parent.name.isdigit():
            barcode = parent.name + barcode
        else:
            break

    barcode = barcode or None
    return barcode


def split_barcode(barcode):
    return barcode[0:3], barcode[3:6], barcode[6:9], barcode[9:13]


def fetch_images_for_ean(ean):
    url = "https://world.openfoodfacts.org/api/v0/product/" \
          "{}.json?fields=images".format(ean)
    images = requests.get(url).json()
    return images


def get_json_for_image(barcode, image_name):
    splitted_barcode = split_barcode(barcode)
    url = "https://static.openfoodfacts.org/images/products/{}/{}/{}/{}/" \
          "{}.json".format(splitted_barcode[0], splitted_barcode[1],
                           splitted_barcode[2], splitted_barcode[3],
                           image_name)
    r = requests.get(url)

    if r.status_code == 404:
        return

    return r.json()


def get_raw_text(data):
    responses = data.get('responses', [])

    if not responses:
        return

    response = responses[0]
    text_annotation = response.get('fullTextAnnotation')

    if not text_annotation:
        return

    text = text_annotation.get('text')

    if text is None:
        return

    return text


def find_packager_codes(text):
    results = []

    for regex_code, regex in PACKAGER_CODE.items():
        for match in regex.finditer(text):
            results.append({
                "text": match.group(),
                "type": regex_code,
            })

    return results


def find_weights(text):
    weight_mentions = []

    for match in WEIGHT_MENTIONS_RE.finditer(text):
        result = {
            'text': match.group(),
        }
        weight_mentions.append(result)

    weight_values = []

    for match in WEIGHT_VALUES_REGEX.finditer(text):
        result = {
            'text': match.group(),
            'value': match.group(1),
            'unit': match.group(2),
        }
        weight_values.append(result)

    result = {}

    if weight_values:
        result['values'] = weight_values

    if weight_mentions:
        result['mentions'] = weight_mentions

    if result:
        return result


def extract_temperature_information(temperature):
    match = TEMPERATURE_REGEX.match(temperature)

    if match:
        result = {}
        value = match.group('value')
        unit = match.group('unit')

        if value:
            result['value'] = value

        if unit:
            result['unit'] = unit

        return result


def find_storage_instructions(text):
    text = text.lower()

    results = []

    for instruction_type, regex in STORAGE_INSTRUCTIONS_REGEX.items():
        for match in regex.finditer(text):
            if match:
                result = {
                    'text': match.group(),
                    'type': instruction_type,
                }

                if instruction_type == 'max':
                    result['max'] = extract_temperature_information(
                        match.group(1))

                elif instruction_type == 'between':
                    result['between'] = {
                        'min': extract_temperature_information(match.group(1)),
                        'max': extract_temperature_information(match.group(2)),
                    }

                results.append(result)

    return results


def find_nutriscore(text):
    results = []
    for match in NUTRISCORE_REGEX.finditer(text):
        results.append({
            "text": match.group(),
        })

    return results


def find_recycling_instructions(text):
    results = []

    for instruction_type, regex_list in RECYCLING_REGEX.items():
        for regex in regex_list:
            for match in regex.finditer(text):
                results.append({
                    'type': instruction_type,
                    'text': match.group(),
                })

    return results


def find_labels(text):
    text = text.lower()

    results = []

    for label_type, regex_list in LABELS_REGEX.items():
        for regex in regex_list:
            for match in regex.finditer(text):
                results.append({
                    'type': label_type,
                    'text': match.group(),
                })

    return results


def find_best_before_date(text):
    # Parse best_before_date
    #        "À consommer de préférence avant",
    results = []

    for type_, regex in BEST_BEFORE_DATE_REGEX.items():
        for match in regex.finditer(text):
            results.append({
                "text": match.group(),
                "type": type_,
            })

    return results


def extract_insights(data):
    text = get_raw_text(data)

    if text is None:
        print("Could not extract OCR text content")
        return

    contiguous_text = text.replace('\n', ' ')

    insights = {}

    weights = find_weights(text)
    packager_codes = find_packager_codes(contiguous_text)
    nutriscore = find_nutriscore(text)
    recycling_instructions = find_recycling_instructions(contiguous_text)
    labels = find_labels(contiguous_text)
    storage_instructions = find_storage_instructions(contiguous_text)
    best_before_date = find_best_before_date(text)

    for key, value in (
            ('weights', weights),
            ('packager_codes', packager_codes),
            ('nutriscore', nutriscore),
            ('recycling_instructions', recycling_instructions),
            ('labels', labels),
            ('storage_instructions', storage_instructions),
            ('best_before_date', best_before_date),
    ):
        if value:
            insights[key] = value

    return insights


def ocr_iter(input_str):
    if len(input_str) == 13 and input_str.isdigit():
        image_data = fetch_images_for_ean(input_str)['product']['images']

        for image_name in image_data.keys():
            if image_name.isdigit():
                print("Getting OCR for image {}".format(image_name))
                data = get_json_for_image(input_str, image_name)

                if data:
                    yield None, data

    else:
        input_path = pathlib.Path(input_str)

        if not input_path.exists():
            print("Unrecognized input: {}".format(input_path))
            return

        if input_path.is_dir():
            for json_path in input_path.glob("**/*.json"):
                with open(str(json_path), 'r') as f:
                    yield json_path, json.load(f)
        else:
            with open(str(input_path), 'r') as f:
                yield input_path, json.load(f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('--output,-o')
    args = parser.parse_args()

    input_ = args.input

    if args.output is not None:
        output = open(args.output, 'w')
    else:
        output = sys.stdout

    with contextlib.closing(output):
        with open('insights.json', 'w') as f:
            for file_path, ocr_json in ocr_iter(input_):
                insights = extract_insights(ocr_json)

                if insights:
                    item = {
                        'insights': insights,
                        'file_path': str(file_path),
                        'code': get_barcode_from_path(file_path),
                    }
                    f.write(json.dumps(item) + '\n')