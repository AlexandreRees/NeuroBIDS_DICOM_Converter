classdef CheckerMoveSine < handle
   properties
       tex
       stimParams
       numFrames       {mustBeNumeric}
       pulseTime       {mustBeNumeric}
       lastPulseTime   {mustBeNumeric}
       phaseDirection  {mustBeNumeric}
       phaseFrameOffset {mustBeNumeric}
   end
   methods (Access = public)
      function obj = CheckerMoveSine(checkerStimParams, pulseTime)
        if nargin>=1  && isfield(checkerStimParams,'mean') ...
                     && isfield(checkerStimParams,'amplitude') ...
                     && isfield(checkerStimParams,'spatialF') ...
                     && isfield(checkerStimParams,'gratingSpeed') ...
                     && isfield(checkerStimParams,'gratingColor') ...                     
                     && isfield(checkerStimParams,'cyclesPerRotation')

            % Passed in stim params
            obj.stimParams = checkerStimParams;
          
        end
	
		if nargin==2
            % Passed in pulse time 
			obj.pulseTime = pulseTime;
		end 
	  end

      function obj = createTextures(obj, diameter,screenProperties)

        cyclePerPixel = obj.stimParams.spatialF*screenProperties.degPerPix; %spatialF in cyclesPerDeg
		radius = diameter/2;
        [X,Y] = meshgrid(-radius(1):1:radius(1),-radius(2):1:radius(2));
        R = sqrt(X.^2+Y.^2);
        T = atan2(-Y,X);
        
        % grating colors
        colorBlackAndWhite = 0;
        colorRedAndGreen   = 2;

        % read the isoluminant R and G values
        % read the isoluminant R and G values
        Redlevel = load('RedLevel.mat');
        Redlevel= (Redlevel.RedLevel);
        Greenlevel = load('GreenLevel.mat');
        Greenlevel = (Greenlevel.GreenLevel);

        half_cod =0.5*255;
        % Calculation for deg/second -> frames/cycle
        % deg/second * cycles/deg * seconds/frame = cycles/frame
        % 1/cycles/frame = frames/cycle

        % number frames for one cycle
        numFrames=round(1/(obj.stimParams.gratingSpeed*obj.stimParams.spatialF*screenProperties.ifi)); % temporal period, in frames, of the drifting grating
        obj.numFrames = numFrames;
        for i=1:numFrames
            phase=(i/numFrames)*2*pi;
            switch obj.stimParams.gratingColor
                case colorBlackAndWhite
                    grating = zeros([size(R), 1]);
                    grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) + obj.stimParams.amplitude*sin(2*pi* cyclePerPixel * R - phase*ones(size(R))) .* sin(2*pi*obj.stimParams.cyclesPerRotation/(2*pi)*T)); 

                case colorRedAndGreen
                    grating = zeros([size(R), 3]);
                    sinMatrix = sin(2*pi* cyclePerPixel * R - phase*ones(size(R))) .* sin(2*pi*obj.stimParams.cyclesPerRotation/(2*pi)*T );
                    grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) + (Redlevel(1)-half_cod)*(sinMatrix.*(sinMatrix >= 0))-(half_cod-Greenlevel(1))*abs(sinMatrix.*(sinMatrix <= 0)));
                    grating(:,:,2) = round(obj.stimParams.mean * ones(size(R)) + (Greenlevel(2)-half_cod)*abs(sinMatrix.*(sinMatrix <= 0))-(half_cod-Redlevel(2))*(sinMatrix.*(sinMatrix >= 0)));
            end
            obj.tex(i) = Screen('MakeTexture', screenProperties.window, grating);
        end

        obj.lastPulseTime = 0;
        obj.phaseDirection = 1;
        obj.phaseFrameOffset = 0;
      end
      
      function texture = getNextTexture(obj, timeProperties)
          
        if obj.lastPulseTime == 0
            obj.lastPulseTime = timeProperties.t;
        end

        if timeProperties.t > obj.lastPulseTime + obj.pulseTime
			obj.phaseDirection = obj.phaseDirection * -1;
            % offset so current frame is same number while going backwards
            obj.phaseFrameOffset = timeProperties.framecount;
			obj.lastPulseTime = timeProperties.t;	
            
        end
                
        if obj.phaseDirection == 1
            texture = obj.tex(mod(timeProperties.framecount,obj.numFrames)+1);
        else
            texture = obj.tex(mod(obj.phaseFrameOffset-(timeProperties.framecount-obj.phaseFrameOffset),obj.numFrames)+1);            
        end
      end
      
   end
end
