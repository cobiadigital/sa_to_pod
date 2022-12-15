import io
import azure.cognitiveservices.speech as speechsdk
import bs4
import re
import os
import time
import boto3
import json
from botocore.exceptions import ClientError
from flask import current_app, url_for

def get_keys(path):
        with open(path) as f:
            return json.load(f)
def get_s3client():
    keys = get_keys(".secret/.s3.json")
    url = keys['url']
    bucket = keys['bucket']
    aws_access_key_id = keys['access_key_id']
    aws_secret_access_key = keys['access_key_secret']
    s3 = boto3.client('s3',
      endpoint_url = url,
      aws_access_key_id = aws_access_key_id,
      aws_secret_access_key = aws_secret_access_key
    )
    return s3

def pollytext(body, voice):

    soup = bs4.BeautifulSoup(body, "html.parser")
    hr_tags = soup("hr")
    for hr_tag in hr_tags:
        hr_tag.name = "break"

    emphasis = soup(["em","i"])
    for emph in emphasis:
        emph.name = "emphasis"
        emph['level'] = "strong"

    text = ""

    for accepted_tag in soup(["p", "break"]):
        text += str(accepted_tag)
    #fix line-break hyphens
    text = re.sub('- \n', '', text)
    text = re.sub('\n', '', text)
    #remove http addresses
    text = re.sub(r'https*? ', '', text)
#     remove page numbers
    text = re.sub(u'\xa0', u' ', text)
    output = re.sub(u'[\u201c\u201d]', '"', text)
    print(len(output))
    sep = '.'
    rest = output

    #remove references
    end = rest.rfind('<p>Reference')
    if (end != -1):

        rest = rest[0:end]
    #Because single invocation of the polly synthesize_speech api can
    # transform text with about 1,500 characters, we are dividing the
    # post into blocks of approximately 1,000 characters.
    textBlocks = []
    while (len(rest) > 5000):
        begin = 0
        end = rest.rfind("</p>", 0, 5000) #rfind looks for the last case of the search term.

        if (end == -1):
            end = rest.rfind(". ", 0, 5000)
            textBlock = rest[begin:end+1]
            rest = rest[end+1:]
            textBlocks.append('''<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="en-US">
                     <voice name="'''+ voice + '''">
                         <prosody rate="0%" pitch="0%">''' + textBlock + "</p></prosody></voice></speak>")
            rest = "<p>" + rest

        else:
            textBlock = rest[begin:end+4]
            rest = rest[end+4:] #Remove the annoying "Dot" that otherwise starts each new block since you no longer start on that index.
            textBlocks.append('''<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="en-US">
                     <voice name="''' + voice + '''">
                         <prosody rate="0%" pitch="0%">''' + textBlock + "</prosody></voice></speak>")
    textBlocks.append('''<speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="en-US">
                     <voice name="''' + voice + '''">
                         <prosody rate="0%" pitch="0%">''' + rest + '</prosody></voice></speak>')
    with open("instance/output.txt", "w") as text:
        # Write the response to the output file.
        text.write(str(textBlocks))
    return textBlocks

# Get text from the console and synthesize to the default speaker.


def synthesize_ssml(speech_client, ssml, voice):
    textBlocks = pollytext(ssml, voice)
    audio_data_list = []
    for textBlock in textBlocks:
        result = speech_client.speak_ssml_async(textBlock).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(textBlock)
            print("Speech synthesized for text")
            audio_data_list.append(result.audio_data)
            time.sleep(2)
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                 if cancellation_details.error_details:
                       print("Error details: {}".format(cancellation_details.error_details))
                       print("Did you set the speech resource key and region values?")
            break
    return b"".join(audio_data_list)

def create_mp3(id, slug, cold_opening, intro_music, intro, body, mid_music, ending, end_music, voice, speech_client):
    print('text of intro')
    print(intro)
    print('END text of intro')
    build_audio = []
    build_audio.append(synthesize_ssml(speech_client, cold_opening, voice))
    with open(os.path.join(current_app.static_folder, 'intro-music-1.mp3'), 'rb') as f:
        intro_music = f.read()
    build_audio.append(intro_music)
    build_audio.append(synthesize_ssml(speech_client, intro, voice))
    build_audio.append(synthesize_ssml(speech_client, body, voice))
    with open(os.path.join(current_app.static_folder, 'mid-music-1.mp3'), 'rb') as f:
        mid_music = f.read()
    build_audio.append(mid_music)
    build_audio.append(synthesize_ssml(speech_client, ending, voice))
    with open(os.path.join(current_app.static_folder, 'end-music-1.mp3'), 'rb') as f:
        end_music = f.read()
    build_audio.append(end_music)

    combined = b"".join(build_audio)

    file_name = str(id) + "_" + slug + ".mp3"
    s3 = get_s3client()
    bucket = 'ai-podcast'
    audiofile = io.BytesIO(combined)
    audio_length = round(audiofile.getbuffer().nbytes / 12000)
    s3.upload_fileobj(audiofile, bucket, file_name)
    #debug code
    #with open(os.path.join(current_app.static_folder, 'combined.mp3'), "wb") as out:
    # Write the response to the output file.
    #    out.write(combined)
    return (file_name, audio_length)

