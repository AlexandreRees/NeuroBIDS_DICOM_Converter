% Stimulus parameters

stimParams.mean= 255*0.5; %black and white
stimParams.amplitude = 255*0.5; % contrast

stimParams.spatialF =0.5; %cycles per d
stimParams.gratingSpeed = 2; %deg per s

% # cycles so that spatialF is same at 5 deg radially and circularly
stimParams.cyclesPerRotation = round(stimParams.spatialF*2*pi*5); % cycles/deg * (2*PI*R) deg where R=5 degrees

% grating colors
colorBlackAndWhite = 0;
colorRedAndGreen   = 2;

stimParams.gratingColor = colorRedAndGreen;
